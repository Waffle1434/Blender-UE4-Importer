import bpy, os, sys, math, importlib, time, zlib
from mathutils import *

cur_dir = os.path.dirname(__file__)
if cur_dir not in sys.path: sys.path.append(cur_dir)

import import_uasset, import_umat, import_umesh
from import_uasset import UAsset, Import, Export, Vector, Euler
from import_umat import TryGetUMaterialImport
from import_umesh import ImportStaticMeshUAsset

hide_noncasting = False
deg2rad = math.radians(1)

def SetupObject(context, name, data=None):
    obj = bpy.data.objects.new(name, data)
    obj.rotation_mode = 'YXZ'
    context.collection.objects.link(obj)
    return obj
def Transform(export:Export, obj, pitch_offset=0):
    props = export.properties

    # Unreal: X+ Forward, Y+ Right, Z+ Up     Blender: X+ Right, Y+ Forward, Z+ Up
    rel_loc = props.TryGetValue('RelativeLocation')
    if rel_loc: obj.location = Vector((rel_loc.y,rel_loc.x,rel_loc.z)) * 0.01
    
    # Unreal: Roll, Pitch, Yaw     File: Pitch, Yaw, Roll     Blender: Pitch, Roll, -Yaw     0,0,0 = fwd, down for lights
    rel_rot = props.TryGetValue('RelativeRotation')
    if rel_rot: obj.rotation_euler = Euler(((rel_rot.x+pitch_offset)*deg2rad, rel_rot.z*deg2rad, -rel_rot.y*deg2rad))

    rel_scale = props.TryGetValue('RelativeScale3D')
    if rel_scale: obj.scale = Vector((rel_scale.y,rel_scale.x,rel_scale.z))
def TryApplyRootComponent(export:Export, obj, pitch_offset=0):
    root_exp = export.properties.TryGetValue('RootComponent')
    if root_exp:
        Transform(root_exp, obj, pitch_offset)
        return True
    return False
def TryGetStaticMesh(static_mesh_comp:Export, import_materials=True):
    mesh = None
    static_mesh = static_mesh_comp.properties.TryGetValue('StaticMesh')
    if static_mesh:
        mesh_name = static_mesh.object_name
        mesh = bpy.data.meshes.get(mesh_name)
        if not mesh:
            mesh_import = static_mesh.import_ref
            if mesh_import:
                mesh_path = static_mesh_comp.asset.ToProjectPath(mesh_import.object_name)
                mesh = ImportStaticMeshUAsset(mesh_path, import_materials)
                if not mesh: print(f"Failed to get Static Mesh \"{mesh_path}\"")
        if import_materials:
            mat_overrides:list[Import] = static_mesh_comp.properties.TryGetValue('OverrideMaterials')
            if mat_overrides:
                hash = 1
                for mat_override in mat_overrides: hash = zlib.adler32(str.encode(mat_override.value.object_name if mat_override.value else "None"), hash)
                override_mesh_name = f"{mesh_name}_{hash:X}"
                override_mesh = bpy.data.meshes.get(override_mesh_name)
                if override_mesh: mesh = override_mesh
                else:
                    mesh = mesh.copy()
                    mesh.name = override_mesh_name
                    for i in range(len(mat_overrides)):
                        mat_override = mat_overrides[i].value
                        if mat_override: mesh.materials[i] = TryGetUMaterialImport(mat_override, mat_mesh=mesh)
    return mesh
def ProcessUMapExport(export:Export, import_meshes=True, import_materials=True):
    match export.export_class_type:
        case 'StaticMeshActor':
            export.ReadProperties(True, False)
            static_mesh_comp = export.properties.TryGetValue('StaticMeshComponent') if import_meshes else None
            mesh = TryGetStaticMesh(static_mesh_comp, import_materials) if static_mesh_comp else None
            
            obj = SetupObject(bpy.context, export.object_name, mesh)
            TryApplyRootComponent(export, obj)
        case 'PointLight' | 'SpotLight':
            export.ReadProperties(True, False)

            match export.export_class_type:
                case 'PointLight': light_type = 'POINT'
                case 'SpotLight': light_type = 'SPOT'
                case _: raise # TODO: Sun Light

            light = bpy.data.lights.new(export.object_name, light_type)
            light_obj = SetupObject(bpy.context, light.name, light)
            TryApplyRootComponent(export, light_obj, -90) # Blender lights are cursed, local Z- Forward, Y+ Up, X+ Right
            
            light_comp = export.properties.TryGetValue('LightComponent')
            if light_comp:
                light_props = light_comp.properties
                light.energy = light_props.TryGetValue('Intensity')
                color = light_props.TryGetValue('LightColor')
                if color: light.color = Color((color.r,color.g,color.b)) / 255.0
                cast = light_props.TryGetValue('CastShadows')
                if cast != None:
                    light.use_shadow = cast
                    if not cast and hide_noncasting: light_obj.hide_viewport = light_obj.hide_render = True
                light.shadow_soft_size = light_props.TryGetValue('SourceRadius', 0.05)

                if light_type == 'SPOT':
                    outer_angle = light_props.TryGetValue('OuterConeAngle')
                    inner_angle = light_props.TryGetValue('InnerConeAngle', 0)
                    light.spot_size = outer_angle * deg2rad
                    light.spot_blend = 1 - (inner_angle / outer_angle)
        case _:
            if export.export_class.class_name == 'BlueprintGeneratedClass':
                export.ReadProperties(True, False)

                bp_obj = SetupObject(bpy.context, export.object_name)
                TryApplyRootComponent(export, bp_obj)
                root_comp = export.properties.TryGetValue('RootComponent')
                root_comp.bl_obj = bp_obj

                bp_comps = export.properties.TryGetValue('BlueprintCreatedComponents')
                if bp_comps:
                    if not hasattr(export.asset, 'import_cache'): export.asset.import_cache = {}

                    bp_path = export.export_class.import_ref.object_name
                    bp_asset = export.asset.import_cache.get(bp_path)
                    if not bp_asset:
                        export.asset.import_cache[bp_path] = bp_asset = UAsset(export.asset.ToProjectPath(bp_path))
                        bp_asset.Read(False)
                        bp_asset.name2exp = {}
                        for exp in bp_asset.exports: bp_asset.name2exp[exp.object_name] = exp
                    
                    for comp in bp_comps:
                        child_export = comp.value
                        #ProcessUMapExport(child_export) # TODO? Can't, need to partly process gend_exp & child_export
                        if child_export.export_class_type == 'StaticMeshComponent':
                            gend_exp = bp_asset.name2exp.get(f"{child_export.object_name}_GEN_VARIABLE")
                            if gend_exp:
                                gend_exp.ReadProperties()

                                mesh = TryGetStaticMesh(gend_exp, import_materials) if import_meshes else None
                                child_export.bl_obj = obj = SetupObject(bpy.context, child_export.object_name, mesh)

                                attach = child_export.properties.TryGetValue('AttachParent') # TODO: unify?
                                if attach:
                                    assert hasattr(attach, 'bl_obj')
                                    obj.parent = attach.bl_obj

                                Transform(gend_exp, obj)
                return
def LoadUMap(filepath, import_meshes=True, import_materials=True):
    t0 = time.time()
    with UAsset(filepath) as asset:
        for export in asset.exports:
            #export.ReadProperties(False, False)
            ProcessUMapExport(export, import_meshes, import_materials)
    if hasattr(asset, 'import_cache'):
        for imp_asset in asset.import_cache.values(): imp_asset.Close()
    print(f"Imported {asset}: {(time.time() - t0) * 1000:.2f}ms")

if __name__ != "import_umap":
    importlib.reload(import_uasset)
    importlib.reload(import_umat)
    importlib.reload(import_umesh)
    #sys.settrace(None) # Disable debugging for faster runtime

    LoadUMap(r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Maps\Example_Stationary.umap", True, True)
    #LoadUMap(r"C:\Users\jdeacutis\Desktop\fSpy\New folder\Blender-UE4-Importer\Samples\Example_Stationary.umap", True, True)
    print("Done")