import os, sys

dir = os.path.dirname(__file__)
if dir not in sys.path: sys.path.append(dir)
from import_uasset import *

hide_noncasting = False
deg2rad = math.radians(1)

def ImportUnrealFbx(filepath, collider_mode='NONE'):
    objs_1 = set(bpy.context.collection.objects)
    bpy.ops.import_scene.fbx(filepath=filepath, use_image_search=False)
    imported_objs = []
    for object in set(bpy.context.collection.objects) - objs_1:
        if object.name.startswith("UCX_"): # Collision
            if collider_mode == 'NONE':
                bpy.data.objects.remove(object)
                continue
            object.display_type = 'WIRE'
            object.hide_render = True
            object.visible_camera = object.visible_diffuse = object.visible_glossy = object.visible_transmission = object.visible_volume_scatter = object.visible_shadow = False
            object.select_set(False)
            object.hide_set(collider_mode == 'HIDE')
        else: imported_objs.append(object)
    return imported_objs

def ArchiveToProjectPath(path): return os.path.join(project_dir, "Content", str(pathlib.Path(path).relative_to("\\Game"))) + ".uasset"
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
def TryGetExtractedImport(imp:Import, extract_dir):
    archive_path = imp.object_name.str
    extracted_imports = {}
    extracted = extracted_imports.get(archive_path)
    if not extracted:
        asset_path = ArchiveToProjectPath(archive_path)
        extracted_path = extract_dir+archive_path
        match type:
            case 'StaticMesh':
                subprocess.run(f"\"{umodel_path}\" -export -gltf -out=\"{extract_dir}\" \"{asset_path}\"")
                #bpy.ops.import_scene.gltf(filepath=extracted_path, merge_vertices=True, import_pack_images=False)
            case 'Texture':
                subprocess.run(f"\"{umodel_path}\" -export -png -out=\"{extract_dir}\" \"{asset_path}\"")
                #bpy.data.images.load(extracted_path, check_existing=True)
            case _: raise
        raise
        extracted_imports[archive_path] = extracted
    return extracted
def TryGetStaticMesh(static_mesh_comp:Export):
    mesh = None
    static_mesh = static_mesh_comp.properties.TryGetValue('StaticMesh')
    if static_mesh:
        mesh_name = static_mesh.object_name.str
        mesh = bpy.data.meshes.get(mesh_name)
        if not mesh:
            mesh_import = static_mesh.import_ref
            if mesh_import:
                mesh_path = os.path.normpath(f"{exported_base_dir}{mesh_import.object_name.str}.FBX")
                return mesh
                mesh = ImportUnrealFbx(mesh_path)[0].data
                mesh.name = mesh_name
                mesh.transform(Euler((0,0,90*deg2rad)).to_matrix().to_4x4()*0.01)
    return mesh
def ProcessSceneExport(export:Export, import_meshes=True):
    match export.export_class_type:
        case 'StaticMeshActor':
            export.ReadProperties()
            static_mesh_comp = export.properties.TryGetValue('StaticMeshComponent') if import_meshes else None
            mesh = TryGetStaticMesh(static_mesh_comp) if static_mesh_comp else None
            
            obj = SetupObject(bpy.context, export.object_name.str, mesh)
            TryApplyRootComponent(export, obj)
        case 'PointLight' | 'SpotLight':
            export.ReadProperties()

            match export.export_class_type:
                case 'PointLight': light_type = 'POINT'
                case 'SpotLight': light_type = 'SPOT'
                case _: raise # TODO: Sun Light

            light = bpy.data.lights.new(export.object_name.str, light_type)
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
                export.ReadProperties()

                bp_obj = SetupObject(bpy.context, export.object_name.str)
                TryApplyRootComponent(export, bp_obj)
                root_comp = export.properties.TryGetValue('RootComponent')
                root_comp.bl_obj = bp_obj

                bp_comps = export.properties.TryGetValue('BlueprintCreatedComponents')
                if bp_comps:
                    if not hasattr(export.asset, 'import_cache'): export.asset.import_cache = {}

                    bp_path = export.export_class.import_ref.object_name.str
                    bp_asset = export.asset.import_cache.get(bp_path)
                    if not bp_asset:
                        export.asset.import_cache[bp_path] = bp_asset = UAsset(ArchiveToProjectPath(bp_path))
                        bp_asset.Read(False)
                        bp_asset.name2exp = {}
                        for exp in bp_asset.exports: bp_asset.name2exp[exp.object_name.str] = exp
                    
                    for comp in bp_comps:
                        child_export = comp.value
                        #ProcessSceneExport(child_export) # TODO? Can't, need to partly process gend_exp & child_export
                        if child_export.export_class_type == 'StaticMeshComponent':
                            gend_exp = bp_asset.name2exp.get(f"{child_export.object_name.str}_GEN_VARIABLE")
                            if gend_exp:
                                gend_exp.ReadProperties()

                                mesh = TryGetStaticMesh(gend_exp)
                                child_export.bl_obj = obj = SetupObject(bpy.context, child_export.object_name.str, mesh)

                                attach = child_export.properties.TryGetValue('AttachParent') # TODO: unify?
                                if attach:
                                    assert hasattr(attach, 'bl_obj')
                                    obj.parent = attach.bl_obj

                                Transform(gend_exp, obj)
                return
def LoadUAssetScene(filepath, import_meshes=True):
    with UAsset(filepath) as asset:
        for export in asset.exports:
            ProcessSceneExport(export, import_meshes)
        if hasattr(asset, 'import_cache'):
            for imp_asset in asset.import_cache.values(): imp_asset.Close()

if __name__ != "import_umap":
    LoadUAssetScene(r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Maps\Example_Stationary.umap", False)
    #LoadUAssetScene(r"C:\Users\jdeacutis\Desktop\fSpy\New folder\Blender-UE4-Importer\Samples\Example_Stationary.umap", False)
    print("Done")