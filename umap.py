import bpy, os, sys, math, importlib, time, zlib
from dataclasses import dataclass
from mathutils import *
from bpy.props import *
from bpy_extras.io_utils import ImportHelper

cur_dir = os.path.dirname(__file__)
if cur_dir not in sys.path: sys.path.append(cur_dir)

import uasset, umat, umesh, register_helper
from uasset import UAsset, Import, Export, FVector, FColor
from umat import TryGetUMaterialImport
from umesh import ImportMeshUAsset

hide_noncasting = False
deg2rad = math.radians(1)

@dataclass
class UMapImportSettings():
    meshes:           bool  = True
    materials:        bool  = True
    cameras:          bool  = True
    lights_point:     bool  = False
    lights_spot:      bool  = True
    lights_dir:       bool  = True
    cubemaps:         bool  = True
    lightprobes:      bool  = True
    force_shadows:    bool  = False
    light_intensity:  float = 1
    light_angle_coef: float = 1

def SetupObject(context, name, data=None):
    obj = bpy.data.objects.new(name, data)
    obj.rotation_mode = 'YXZ'
    obj.empty_display_type = 'ARROWS'
    context.collection.objects.link(obj)
    return obj
def Transform(export:Export, obj, pitch_offset=0, def_scale=FVector(1,1,1), scale=1):
    props = export.properties

    # Unreal: X+ Forward, Y+ Right, Z+ Up     Blender: X+ Right, Y+ Forward, Z+ Up
    if rel_loc := props.TryGetValue('RelativeLocation'): obj.location = Vector((rel_loc.y,rel_loc.x,rel_loc.z)) * 0.01
    
    # Unreal: Roll, Pitch, Yaw     File: Pitch, Yaw, Roll     Blender: Pitch, Roll, -Yaw     0,0,0 = fwd, down for lights
    if rel_rot := props.TryGetValue('RelativeRotation'): obj.rotation_euler = Euler(((rel_rot.x+pitch_offset)*deg2rad, rel_rot.z*deg2rad, -rel_rot.y*deg2rad))

    rel_scale = props.TryGetValue('RelativeScale3D', def_scale)
    obj.scale = Vector((rel_scale.y,rel_scale.x,rel_scale.z)) * scale
def TryApplyRootComponent(export:Export, obj, pitch_offset=0, def_scale=FVector(1,1,1), scale=1):
    if root_export := export.properties.TryGetValue('RootComponent'):
        root_export.ReadProperties(False)
        Transform(root_export, obj, pitch_offset, def_scale, scale)
        return True
    return False
def TryGetMesh(static_mesh_comp:Export, m_type, import_materials=True):
    mesh = None
    if mesh_prop := static_mesh_comp.properties.TryGetValue(m_type):
        mesh_name = mesh_prop.object_name
        mesh = bpy.data.meshes.get(mesh_name)
        if not mesh or not mesh.get('UAsset'):
            if mesh_import := mesh_prop.import_ref:
                mesh_path = static_mesh_comp.asset.ToProjectPath(mesh_import.object_name)
                mesh = ImportMeshUAsset(mesh_path, static_mesh_comp.asset.uproject, import_materials)
                if not mesh: print(f"Failed to get Mesh \"{mesh_path}\"")
        if import_materials:
            mat_overrides:list[Import] = static_mesh_comp.properties.TryGetValue('OverrideMaterials')
            if mat_overrides:
                hash = 1
                for mat_override in mat_overrides: hash = zlib.adler32(str.encode(mat_override.value.object_name if mat_override.value else "None"), hash)
                override_mesh_name = f"{mesh_name}_{hash:X}"
                if override_mesh := bpy.data.meshes.get(override_mesh_name): mesh = override_mesh
                else:
                    mesh = mesh.copy()
                    mesh.name = override_mesh_name
                    c_override = len(mat_overrides)
                    if c_override > len(mesh.materials): print(f"Error: More overrides ({c_override}) than materials ({len(mesh.materials)})")
                    else:
                        for i in range(c_override):
                            if mat_override := mat_overrides[i].value: mesh.materials[i] = TryGetUMaterialImport(mat_override, mesh)
    return mesh
def ProcessUMapExport(export:Export, cfg:UMapImportSettings):
    if type(export.export_class) is not uasset.Import: return
    match export.export_class.class_name:
        case 'Class':
            match export.export_class_type:
                case 'StaticMeshActor':
                    export.ReadProperties(True)
                    mesh_comp = export.properties.TryGetValue('StaticMeshComponent') if cfg.meshes else None
                    mesh = TryGetMesh(mesh_comp, 'StaticMesh', cfg.materials) if mesh_comp else None
                    obj = SetupObject(bpy.context, export.object_name, mesh)
                    TryApplyRootComponent(export, obj)
                case 'SkeletalMeshActor':
                    export.ReadProperties(True)
                    mesh_comp = export.properties.TryGetValue('SkeletalMeshComponent') if cfg.meshes else None
                    mesh = TryGetMesh(mesh_comp, 'SkeletalMesh', cfg.materials) if mesh_comp else None
                    obj = bpy.data.objects[mesh.name]
                    #obj = SetupObject(bpy.context, export.object_name, mesh)
                    TryApplyRootComponent(export, obj)
                case 'PointLight' | 'SpotLight' | 'DirectionalLight':
                    rot_off = -90
                    light_intensity = cfg.light_intensity
                    match export.export_class_type:
                        case 'PointLight':
                            if not cfg.lights_point: return
                            light_type = 'POINT'
                        case 'SpotLight':
                            if not cfg.lights_spot: return
                            light_type = 'SPOT'
                        case 'DirectionalLight':
                            if not cfg.lights_dir: return
                            light_type = 'SUN'
                            light_intensity *= 100
                            rot_off = 0

                    export.ReadProperties(True)

                    light = bpy.data.lights.new(export.object_name, light_type)
                    light_obj = SetupObject(bpy.context, light.name, light)
                    TryApplyRootComponent(export, light_obj, rot_off) # Blender lights are cursed, local Z- Forward, Y+ Up, X+ Right
                    
                    if export.export_class_type == 'DirectionalLight': light_obj.rotation_euler.rotate_axis('X', math.radians(90))
                    
                    if light_comp := export.properties.TryGetValue('LightComponent'): # Export
                        light_props = light_comp.properties
                        light.energy = 0.01 * light_intensity * light_props.TryGetValue('Intensity', 5000) # pre 4.19 is unitless
                        color:FColor = light_props.TryGetValue('LightColor', FColor(255,255,255,255))
                        light.color = Color((color.r,color.g,color.b)) / 255.0
                        cast = light_props.TryGetValue('CastShadows', True)
                        light.use_shadow = cast or cfg.force_shadows
                        if not cast and hide_noncasting: light_obj.hide_viewport = light_obj.hide_render = True
                        light.shadow_soft_size = light_props.TryGetValue('SourceRadius', 0.05)

                        if light_type == 'SPOT':
                            outer_angle = light_props.TryGetValue('OuterConeAngle', 44)
                            inner_angle = light_props.TryGetValue('InnerConeAngle', 0)
                            light.spot_size = 2 * cfg.light_angle_coef * outer_angle * deg2rad
                            light.spot_blend = 1 - (inner_angle / outer_angle)
                case 'BoxReflectionCapture':
                    if not cfg.cubemaps: return
                    export.ReadProperties(False)

                    probe = bpy.data.lightprobes.new(export.object_name, 'CUBE')
                    probe.influence_type = 'BOX'
                    probe.influence_distance = 1

                    if (cap_props := export.properties.TryGetProperties('CaptureComponent')) and (box_props := cap_props.TryGetProperties('PreviewCaptureBox')):
                        if box_ext := box_props.TryGetValue('BoxExtent'): probe.falloff = 1 - max(box_ext.x, max(box_ext.y, box_ext.z))

                    obj = SetupObject(bpy.context, export.object_name, probe)
                    TryApplyRootComponent(export, obj, def_scale=FVector(1000,1000,400), scale=0.01)

                    if cfg.lightprobes:
                        irr = bpy.data.lightprobes.new(export.object_name, 'GRID')
                        irr.influence_distance = 1 / (1 - probe.falloff) - 1
                        obj2 = SetupObject(bpy.context, f"{export.object_name}_irridance", irr)
                        TryApplyRootComponent(export, obj2, def_scale=FVector(1000,1000,400), scale=0.01*(1 - probe.falloff))
                case 'CameraActor':
                    if cfg.cameras:
                        export.ReadProperties(True)
                        if cam_props := export.properties.TryGetProperties('CameraComponent'): h_fov = cam_props.TryGetValue('FieldOfView', 90)
                        else: h_fov = 90

                        cam = bpy.data.cameras.new(name=export.object_name)
                        cam.display_size, cam.sensor_fit, cam.lens_unit = (0.5, 'HORIZONTAL', 'FOV')
                        cam.angle = math.radians(h_fov)

                        obj = SetupObject(bpy.context, export.object_name, cam)
                        TryApplyRootComponent(export, obj, 90)
                #case _: print(f"Skipping \"{export.export_class_type}\"")
        case 'BlueprintGeneratedClass':
            export.ReadProperties(True)

            bp_obj = SetupObject(bpy.context, export.object_name)
            TryApplyRootComponent(export, bp_obj)
            if root_comp := export.properties.TryGetValue('RootComponent'): root_comp.bl_obj = bp_obj

            if bp_comps := export.properties.TryGetValue('BlueprintCreatedComponents'):
                if not hasattr(export.asset, 'import_cache'): export.asset.import_cache = {}

                bp_path = export.export_class.import_ref.object_name
                if bp_path.startswith("/Engine/"): return
                bp_asset = export.asset.import_cache.get(bp_path)
                if not bp_asset:
                    bp_asset = UAsset(export.asset.ToProjectPath(bp_path), False, export.asset.uproject)
                    bp_asset = bp_asset.__enter__()
                    bp_asset.name2exp = {}
                    for exp in bp_asset.exports: bp_asset.name2exp[exp.object_name] = exp
                    export.asset.import_cache[bp_path] = bp_asset
                
                for comp in bp_comps:
                    child_export = comp.value
                    #ProcessUMapExport(child_export) # TODO? Can't, need to partly process gend_exp & child_export
                    if child_export.export_class_type == 'StaticMeshComponent':
                        gend_exp = bp_asset.name2exp.get(f"{child_export.object_name}_GEN_VARIABLE")
                        if gend_exp:
                            gend_exp.ReadProperties()

                            mesh = TryGetMesh(gend_exp, 'StaticMesh', cfg.materials) if cfg.meshes else None
                            child_export.bl_obj = obj = SetupObject(bpy.context, child_export.object_name, mesh)

                            if attach := child_export.properties.TryGetValue('AttachParent'): # TODO: unify?
                                assert hasattr(attach, 'bl_obj')
                                obj.parent = attach.bl_obj

                            Transform(gend_exp, obj)
def LoadUMap(filepath, cfg=UMapImportSettings()):
    t0 = time.time()

    obj_count = len(bpy.data.objects)
    mesh_count = len(bpy.data.meshes)
    mat_count = len(bpy.data.materials)
    light_count = len(bpy.data.lights)

    with UAsset(filepath) as asset:
        bpy.context.window_manager.progress_begin(0, len(asset.exports))
        for i, export in enumerate(asset.exports):
            #export.ReadProperties(False, False)
            ProcessUMapExport(export, cfg)
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

    meshes:           BoolProperty(name="Meshes",             default=True, description="Static and Skeletal Meshes.")
    materials:        BoolProperty(name="Materials",          default=True, description="Mesh Materials (slowest part).")
    cameras:          BoolProperty(name="Cameras",            default=True)
    lights_point:     BoolProperty(name="Point Lights",       default=False)
    lights_spot:      BoolProperty(name="Spot Lights",        default=True)
    lights_dir:       BoolProperty(name="Directional Lights", default=True)
    cubemaps:         BoolProperty(name="Cubemaps",           default=True, description="Box Reflection Volumes")
    lightprobes:      BoolProperty(name="Irradance Volumes",  default=True, description="Add Light Probe Volumes inside Box Reflection Volumes.")
    force_shadows:    BoolProperty(name="Force Shadows",      default=False, description="Force all lights to cast shadows.")
    light_intensity:  FloatProperty(name="Light Brightness",  default=1, min=0, description="Optional multiplier for light intensity.")
    light_angle_coef: FloatProperty(name="Light Angle",       default=1, min=0, description="Optional multiplier for spotlight angle.")

    def execute(self, context):
        for file in self.files:
            if file.name != "":
                cfg = UMapImportSettings(self.meshes, self.materials, self.cameras, self.lights_point, self.lights_spot, self.lights_dir, 
                                   self.cubemaps, self.lightprobes, self.force_shadows, self.light_intensity, self.light_angle_coef)
                LoadUMap(self.directory + file.name, cfg)
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

    #LoadUMap(r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Maps\Example_Stationary.umap")
    #LoadUMap(r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Maps\Overview.umap")
    #LoadUMap(r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Maps\Example_Stationary_2.umap")
    #LoadUMap(r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\ModSci_Engineer\Maps\Example_Stationary.umap")
    #LoadUMap(r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\ModSci_Engineer\Maps\Example_Stationary_427.umap")
    #LoadUMap(r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\FPS_Weapon_Bundle\Maps\Weapons_Showcase.umap")
    #LoadUMap(r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\StarterBundle\ModularScifiProps\Maps\Promo.umap")
    #LoadUMap(r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\StarterBundle\ModularScifiProps\Maps\Overview_Props.umap")
    #LoadUMap(r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\StarterBundle\CollectionMaps\Map1.umap")
    LoadUMap(r"C:/Users/jdeacutis/Documents/Unreal Projects/Assets/Content/Military_VOL3_Checkpoint/Maps/Demonstration.umap")
    
    #print(dict(sorted(uasset.struct_counts.items(), key=lambda item: item[1])))
    print("Done")