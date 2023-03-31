import bpy, os, sys, math, importlib, time, zlib
from mathutils import *
from bpy.props import *
from bpy_extras.io_utils import ImportHelper

cur_dir = os.path.dirname(__file__)
if cur_dir not in sys.path: sys.path.append(cur_dir)

import uasset, umat, umesh, register_helper
from uasset import UAsset, Import, Export, Vector, Euler, FColor
from umat import TryGetUMaterialImport
from umesh import ImportStaticMeshUAsset

hide_noncasting = False
deg2rad = math.radians(1)

def SetupObject(context, name, data=None):
    obj = bpy.data.objects.new(name, data)
    obj.rotation_mode = 'YXZ'
    context.collection.objects.link(obj)
    return obj
def Transform(export:Export, obj, pitch_offset=0, scale=1):
    props = export.properties

    # Unreal: X+ Forward, Y+ Right, Z+ Up     Blender: X+ Right, Y+ Forward, Z+ Up
    rel_loc = props.TryGetValue('RelativeLocation')
    if rel_loc: obj.location = Vector((rel_loc.y,rel_loc.x,rel_loc.z)) * 0.01
    
    # Unreal: Roll, Pitch, Yaw     File: Pitch, Yaw, Roll     Blender: Pitch, Roll, -Yaw     0,0,0 = fwd, down for lights
    rel_rot = props.TryGetValue('RelativeRotation')
    if rel_rot: obj.rotation_euler = Euler(((rel_rot.x+pitch_offset)*deg2rad, rel_rot.z*deg2rad, -rel_rot.y*deg2rad))

    rel_scale = props.TryGetValue('RelativeScale3D')
    if rel_scale: obj.scale = Vector((rel_scale.y,rel_scale.x,rel_scale.z)) * scale
def TryApplyRootComponent(export:Export, obj, pitch_offset=0, scale=1):
    root_exp:Export = export.properties.TryGetValue('RootComponent')
    if root_exp:
        root_exp.ReadProperties(False, False)
        Transform(root_exp, obj, pitch_offset, scale)
        return True
    return False
def TryGetStaticMesh(static_mesh_comp:Export, import_materials=True):
    mesh = None
    static_mesh = static_mesh_comp.properties.TryGetValue('StaticMesh')
    if static_mesh:
        mesh_name = static_mesh.object_name
        mesh = bpy.data.meshes.get(mesh_name)
        if not mesh or not mesh.get('UAsset'):
            mesh_import = static_mesh.import_ref
            if mesh_import:
                mesh_path = static_mesh_comp.asset.ToProjectPath(mesh_import.object_name)
                mesh = ImportStaticMeshUAsset(mesh_path, static_mesh_comp.asset.uproject, import_materials)
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
                        if mat_override: mesh.materials[i] = TryGetUMaterialImport(mat_override, mesh)
    return mesh
def ProcessUMapExport(export:Export, import_meshes=True, import_materials=True, import_lights_point=True, import_lights_spot=True, import_cubemaps=True, 
                      force_shadows=False, light_intensity=1, light_angle_coef=1):
    match export.export_class_type:
        case 'StaticMeshActor':
            export.ReadProperties(True, False)
            static_mesh_comp = export.properties.TryGetValue('StaticMeshComponent') if import_meshes else None
            mesh = TryGetStaticMesh(static_mesh_comp, import_materials) if static_mesh_comp else None
            
            obj = SetupObject(bpy.context, export.object_name, mesh)
            TryApplyRootComponent(export, obj)
        case 'PointLight' | 'SpotLight' | 'DirectionalLight':
            rot_off = -90
            match export.export_class_type:
                case 'PointLight':
                    light_type = 'POINT'
                    if not import_lights_point: return
                case 'SpotLight':
                    light_type = 'SPOT'
                    if not import_lights_spot: return
                case 'DirectionalLight':
                    light_type = 'SUN'
                    light_intensity = 100
                    rot_off = 0

            export.ReadProperties(True, False)

            light = bpy.data.lights.new(export.object_name, light_type)
            light_obj = SetupObject(bpy.context, light.name, light)
            TryApplyRootComponent(export, light_obj, rot_off) # Blender lights are cursed, local Z- Forward, Y+ Up, X+ Right
            
            if export.export_class_type == 'DirectionalLight': light_obj.rotation_euler.rotate_axis('X', math.radians(90))
            
            light_comp:Export = export.properties.TryGetValue('LightComponent')
            if light_comp:
                light_props = light_comp.properties
                light.energy = 0.01 * light_intensity * light_props.TryGetValue('Intensity', 5000) # pre 4.19 is unitless
                color:FColor = light_props.TryGetValue('LightColor', FColor(255,255,255,255))
                light.color = Color((color.r,color.g,color.b)) / 255.0
                cast = light_props.TryGetValue('CastShadows', True)
                light.use_shadow = cast or force_shadows
                if not cast and hide_noncasting: light_obj.hide_viewport = light_obj.hide_render = True
                light.shadow_soft_size = light_props.TryGetValue('SourceRadius', 0.05)

                if light_type == 'SPOT':
                    outer_angle = light_props.TryGetValue('OuterConeAngle', 44)
                    inner_angle = light_props.TryGetValue('InnerConeAngle', 0)
                    light.spot_size = 2 * light_angle_coef * outer_angle * deg2rad
                    light.spot_blend = 1 - (inner_angle / outer_angle)
        case 'BoxReflectionCapture':
            if not import_cubemaps: return
            export.ReadProperties(False, False)

            probe = bpy.data.lightprobes.new(export.object_name, 'CUBE')
            probe.influence_type = 'BOX'
            probe.influence_distance = 1

            cap_props = export.properties.TryGetProperties('CaptureComponent')
            if cap_props:
                box_props = cap_props.TryGetProperties('PreviewCaptureBox')
                if box_props:
                    box_ext = box_props.TryGetValue('BoxExtent')
                    if box_ext: probe.falloff = 1 - max(box_ext.x, max(box_ext.y, box_ext.z))

            obj = SetupObject(bpy.context, export.object_name, probe)
            TryApplyRootComponent(export, obj, scale=0.01)
        case _:
            if export.export_class_type == 'BlueprintGeneratedClass':
                export.ReadProperties(True, False)

                bp_obj = SetupObject(bpy.context, export.object_name)
                TryApplyRootComponent(export, bp_obj)
                root_comp = export.properties.TryGetValue('RootComponent')
                if root_comp: root_comp.bl_obj = bp_obj

                bp_comps = export.properties.TryGetValue('BlueprintCreatedComponents')
                if bp_comps:
                    if not hasattr(export.asset, 'import_cache'): export.asset.import_cache = {}

                    bp_path = export.export_class.import_ref.object_name
                    if bp_path.startswith("/Engine/"): return
                    bp_asset = export.asset.import_cache.get(bp_path)
                    if not bp_asset:
                        export.asset.import_cache[bp_path] = bp_asset = UAsset(export.asset.ToProjectPath(bp_path), uproject=export.asset.uproject)
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
def LoadUMap(filepath, import_meshes=True, import_materials=True, import_lights_point=True, import_lights_spot=True, import_cubemaps=True, 
             force_shadows=False, light_intensity=1, light_angle_coef=1):
    t0 = time.time()

    obj_count = len(bpy.data.objects)
    mesh_count = len(bpy.data.meshes)
    mat_count = len(bpy.data.materials)
    light_count = len(bpy.data.lights)

    with UAsset(filepath) as asset:
        bpy.context.window_manager.progress_begin(0, len(asset.exports))
        for i, export in enumerate(asset.exports):
            #export.ReadProperties(False, False)
            ProcessUMapExport(export, import_meshes, import_materials, import_lights_point, import_lights_spot, import_cubemaps, force_shadows, light_intensity, light_angle_coef)
            bpy.context.window_manager.progress_update(i)
        bpy.context.window_manager.progress_end()
    if hasattr(asset, 'import_cache'):
        for imp_asset in asset.import_cache.values(): imp_asset.Close()
    print(f"Imported {asset}: {(time.time() - t0) * 1000:.2f}ms")
    print(f"{len(bpy.data.objects) - obj_count} Objects, {len(bpy.data.meshes) - mesh_count} Meshes, {len(bpy.data.materials) - mat_count} Materials, {len(bpy.data.lights) - light_count} Lights")
    if len(bpy.data.lights) > 128: print(f"Warning, Exceeded Eevee's 128 Light Limit! ({len(bpy.data.lights)})")

def menu_import_umap(self, context): self.layout.operator(ImportUMap.bl_idname, text="UE Map (.umap)")
class ImportUMap(bpy.types.Operator, ImportHelper):
    """Import Unreal Engine umap File"""
    bl_idname    = "import.umap"
    bl_label     = "Import"
    filename_ext = ".umap"
    filter_glob: StringProperty(default="*.umap", options={'HIDDEN'}, maxlen=255)
    files:       CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN','SKIP_SAVE'})
    directory:   StringProperty(options={'HIDDEN'})

    meshes:           BoolProperty(name="Meshes",        default=True)
    materials:        BoolProperty(name="Materials",     default=True, description="Import Mesh Materials (this is usually the slowest part).")
    lights_point:     BoolProperty(name="Point Lights",  default=False)
    lights_spot:      BoolProperty(name="Spot Lights",   default=True)
    cubemaps:         BoolProperty(name="Cubemaps",      default=True)
    force_shadows:    BoolProperty(name="Force Shadows", default=False, description="Force all lights to cast shadows.")
    light_intensity:  FloatProperty(name="Light Brightness", default=1,   min=0, description="Optional multiplier for light intensity.")
    light_angle_coef: FloatProperty(name="Light Angle",      default=1,   min=0, description="Optional multiplier for spotlight angle.")

    def execute(self, context):
        for file in self.files:
            if file.name != "": LoadUMap(self.directory + file.name, self.meshes, self.materials, self.lights_point, self.lights_spot, 
                                         self.cubemaps, self.force_shadows, self.light_intensity, self.light_angle_coef)
        return {'FINISHED'}

reg_classes = ( ImportUMap, )

def register():
    register_helper.RegisterClasses(reg_classes)
    register_helper.RegisterDrawFnc(bpy.types.TOPBAR_MT_file_import, ImportUMap, menu_import_umap)
def unregister():
    register_helper.TryUnregisterClasses(reg_classes)
    register_helper.UnregisterDrawFnc(bpy.types.TOPBAR_MT_file_import, ImportUMap, menu_import_umap)

if __name__ != "umap":
    importlib.reload(uasset)
    importlib.reload(umat)
    importlib.reload(umesh)
    unregister()
    register()

    #sys.settrace(None) # Disable debugging for faster runtime

    #LoadUMap(r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Maps\Example_Stationary.umap", True, True)
    #LoadUMap(r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Maps\Overview.umap", True, True)
    #LoadUMap(r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Maps\Example_Stationary_2.umap", True, True)
    #LoadUMap(r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\ModSci_Engineer\Maps\Example_Stationary.umap", True, True)
    #LoadUMap(r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\ModSci_Engineer\Maps\Example_Stationary_427.umap", True, True)
    print("Done")