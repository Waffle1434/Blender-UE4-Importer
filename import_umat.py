from __future__ import annotations
import bpy, sys, time, os, pathlib, subprocess, importlib
from struct import *
from mathutils import *

cur_dir = os.path.dirname(__file__)
if cur_dir not in sys.path: sys.path.append(cur_dir)
import import_uasset
from import_uasset import UAsset, Import, Export, Properties

project_dir = r"F:\Projects\Unreal Projects\Assets"
umodel_path = cur_dir + r"\umodel.exe"

logging = True
mute_ior = True
mute_fresnel = True

project_dir = os.path.normpath(project_dir)
extract_dir = os.path.join(project_dir, "Export")
extracted_imports = {}

filepath = pathlib.Path(cur_dir) / "UE_nodes.blend"
node_tree_path = filepath / "NodeTree"
with bpy.data.libraries.load(str(filepath)) as (data_from, data_to):
    for node_group in data_from.node_groups:
        bpy.ops.wm.link(filepath=str(node_tree_path / node_group), directory=str(node_tree_path), filename=node_group)

def ArchiveToProjectPath(path): return os.path.join(project_dir, "Content", str(pathlib.Path(path).relative_to("\\Game"))) + ".uasset"
def TryGetExtractedImport(imp:Import, extract_dir):
    archive_path = imp.import_ref.object_name.str
    extracted = extracted_imports.get(archive_path)
    if not extracted:
        match imp.class_name: # TODO: unify
            case 'Texture2D': extension = "png"
            case _: raise
        extracted_path = os.path.normpath(extract_dir + archive_path + f".{extension}")
        if not os.path.exists(extracted_path):
            asset_path = ArchiveToProjectPath(archive_path)
            extract_dir = os.path.join(extract_dir, "Game")
            subprocess.run(f"\"{umodel_path}\" -export -{extension} -out=\"{extract_dir}\" \"{asset_path}\"")
        match imp.class_name:
            case 'Texture2D':
                try: extracted = bpy.data.images.load(extracted_path, check_existing=True)
                except:
                    extracted = None
                    pass
        extracted_imports[archive_path] = extracted
    return extracted

class UE2BlenderNodeMapping():
    def __init__(self, bl_idname, subtype=None, label=None, hide=True, inputs=None, outputs=None, color=None):
        self.bl_idname = bl_idname
        self.subtype = subtype
        self.label = label
        self.hide = hide
        self.inputs = inputs
        self.outputs = outputs
        self.color = color
class NodeData():
    def __init__(self, export, classname=None, node=None, link_indirect=None, input_remap=None):
        self.export = export
        self.classname = classname if classname else export.export_class_type
        self.node = node
        self.link_indirect = link_indirect
        self.input_remap = input_remap
class GraphData(): # TODO: redundant, only returned node_guids used
    def __init__(self):
        self.nodes_data = {}
        self.node_guids = {}

default_mapping = UE2BlenderNodeMapping('ShaderNodeMath', label="UNKNOWN", color=Color((1,0,0)))
UE2BlenderNode_dict = {
    'Material' : UE2BlenderNodeMapping('ShaderNodeBsdfPrincipled', hide=False, inputs={ 'BaseColor':'Base Color','Metallic':'Metallic','Specular':'Specular','Roughness':'Roughness',
        'EmissiveColor':'Emission','Opacity':'Alpha','OpacityMask':'Alpha','Normal':'Normal','Refraction':'IOR' }),
    'MaterialExpressionAdd' : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='ADD', inputs={'A':0,'B':1}),
    'MaterialExpressionMultiply' : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='MULTIPLY', inputs={'A':0,'B':1}),
    'MaterialExpressionConstant' : UE2BlenderNodeMapping('ShaderNodeValue', hide=False),
    'MaterialExpressionScalarParameter' : UE2BlenderNodeMapping('ShaderNodeValue', hide=False),
    'MaterialExpressionConstant3Vector' : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='RGBA', hide=False, outputs={'RGB':0,'R':1,'G':2,'B':3,'A':4}),
    'MaterialExpressionVectorParameter' : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='RGBA', hide=False, outputs={'RGB':0,'R':1,'G':2,'B':3,'A':4}),
    'MaterialExpressionStaticSwitchParameter' : UE2BlenderNodeMapping('ShaderNodeMixRGB', label="Switch", hide=False, inputs={'A':2,'B':1}),
    'MaterialExpressionAppendVector' : UE2BlenderNodeMapping('ShaderNodeCombineXYZ', label="Append", inputs={'A':0,'B':1}),
    'MaterialExpressionLinearInterpolate' : UE2BlenderNodeMapping('ShaderNodeMixRGB', label="Lerp", inputs={'A':1,'B':2,'Alpha':0}),
    'MaterialExpressionClamp' : UE2BlenderNodeMapping('ShaderNodeClamp', inputs={'Input':0,'Min':1,'Max':2}),
    'MaterialExpressionPower' : UE2BlenderNodeMapping('ShaderNodeMath', subtype='POWER', inputs={'Base':0,'Exponent':1}),
    'MaterialExpressionTextureSampleParameter2D' : UE2BlenderNodeMapping('ShaderNodeTexImage', hide=False, inputs={'Coordinates':0}),
    'MaterialExpressionTextureCoordinate' : UE2BlenderNodeMapping('ShaderNodeUVMap', hide=False),
    'MaterialExpressionDesaturation' : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='Desaturation', inputs={'Input':0,'Fraction':1}),
    'MaterialExpressionComment' : UE2BlenderNodeMapping('NodeFrame'),
    'MaterialExpressionFresnel' : UE2BlenderNodeMapping('ShaderNodeFresnel', hide=False),
    'CheapContrast_RGB' : UE2BlenderNodeMapping('ShaderNodeBrightContrast', hide=False, inputs={'FunctionInputs':('Color','Contrast')}),
    'BlendAngleCorrectedNormals' : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='BlendAngleCorrectedNormals', hide=False, inputs={'FunctionInputs':(0,1)}),
}
class_blacklist = { 'SceneThumbnailInfoWithPrimitive', 'MetaData', 'MaterialExpressionPanner' }
material_classes = { 'Material', 'MaterialInstanceConstant' }
node_whitelist = { 'ShaderNodeBsdfPrincipled', 'ShaderNodeOutputMaterial' }
param_x = 'MaterialExpressionEditorX'
param_y = 'MaterialExpressionEditorY'

def DeDuplicateName(name):
    i = name.rfind('.')
    return name[:i] if i >= 0 else name
def GuessBaseDir(filename): return filename[:filename.find("Game")] # Unreal defaults to starting path with "Game" on asset export
def SetupNode(node_tree, name, mapping, node_data): # TODO: inline
    node = node_tree.nodes.new(mapping.bl_idname)
    node.name = name
    node.hide = mapping.hide
    SetNodePos(node, param_x, param_y, node_data.export.properties)
    if mapping.subtype:
        if mapping.bl_idname == 'ShaderNodeGroup': node.node_tree = bpy.data.node_groups[mapping.subtype]
        else: node.operation = mapping.subtype
    if mapping.label: node.label = mapping.label
    node.use_custom_color = mapping.color != None
    if mapping.color: node.color = mapping.color

    match mapping.bl_idname:
        case 'ShaderNodeTexImage':
            rgb_in = node.outputs['Color']
            if node_data.export.properties.TryGetValue('SamplerType') == 'SAMPLERTYPE_Normal':
                rgb2n = node_tree.nodes.new('ShaderNodeGroup')
                rgb2n.node_tree = bpy.data.node_groups['RGBtoNormal']
                rgb2n.hide = True
                SetNodePos(rgb2n, param_x, param_y, node_data.export.properties)
                rgb2n.location += Vector((0,30))
                node_tree.links.new(node.outputs['Color'], rgb2n.inputs['RGB'])
                rgb_in = rgb2n.outputs['Normal']

            rgba = node_tree.nodes.new('ShaderNodeGroup')
            rgba.node_tree = bpy.data.node_groups['RGBA']
            rgba.hide = True # TODO: set position here
            rgba.location = node.location + Vector((120,-32))
            node_tree.links.new(rgb_in, rgba.inputs['RGB'])
            node_tree.links.new(node.outputs['Alpha'], rgba.inputs['A'])
            node_data.link_indirect = rgba.outputs
        case 'ShaderNodeMixRGB':
            node.inputs['Fac'].default_value = 0
    return node
def SetNodePos(node, param_x, param_y, params:Properties): node.location = (params.TryGetValue(param_x,0), -params.TryGetValue(param_y,0))
def CreateNode(exp:Export, mat, nodes_data, graph_data, mat_mesh):
    name = exp.object_name.FullName()
    classname = exp.export_class_type # TODO: inline?
    nodes_data[name] = node_data = NodeData(exp)
    params = exp.properties

    if classname in class_blacklist: return None # TODO: iterate material expression array instead

    if classname == 'MaterialExpressionMaterialFunctionCall': # TODO: import subtree from unreal directory
        classname = params.TryGetValue('MaterialFunction').object_name.FullName()
    node_data.classname = classname

    mapping = UE2BlenderNode_dict.get(classname)
    if not mapping:
        print(f"UNKNOWN CLASS: {classname}")
        mapping = default_mapping
    
    node_data.node = node = SetupNode(mat.node_tree, name, mapping, node_data)

    sx, sy = (params.TryGetValue('SizeX'), params.TryGetValue('SizeY'))
    if sx != None: node.width = sx
    if sy != None: node.height = sy
    txt, param_name = (params.TryGetValue('Text'), params.TryGetValue('ParameterName'))
    if txt: node.label = txt
    elif param_name: node.label = param_name
    value = params.TryGetValue('DefaultValue')
    if value == None: value = params.TryGetValue('Constant')
    if value != None: # TODO: move to mapping class?
        match classname:
            case 'MaterialExpressionScalarParameter':
                node.outputs[0].default_value = value
            case 'MaterialExpressionVectorParameter' | 'MaterialExpressionConstant3Vector':
                node.inputs['RGB'].default_value = value.ToTuple()
                node.inputs['A'].default_value = value.a
            case 'MaterialExpressionStaticSwitchParameter':
                node.inputs['Fac'].default_value = 1 if value else 0
    match classname:
        case 'MaterialExpressionTextureCoordinate':
            uv_i = params.TryGetValue('CoordinateIndex')
            if uv_i != None:
                if mat_mesh == None: mat_mesh = bpy.context.object.data # TODO: less fragile?
                try: node.uv_map = mat_mesh.uv_layers.keys()[uv_i]
                except:
                    print(f"Failed to use UV{uv_i} from mesh")
                    pass
        case 'MaterialExpressionTextureSampleParameter2D':
            tex_imp = params.TryGetValue('Texture')
            if tex_imp:
                tex = TryGetExtractedImport(tex_imp, extract_dir)
                if tex:
                    node.image = tex
                    if params.TryGetValue('SamplerType') == 'SAMPLERTYPE_Normal':
                        node.image.colorspace_settings.name, node.interpolation = ('Non-Color', 'Smart')
                else: print(f"Missing Texture \"{tex_imp.import_ref.object_name.str}\"")
    expr_guid = params.TryGetValue('ExpressionGUID')
    if expr_guid: graph_data.node_guids[expr_guid] = node_data
    return node_data
def LinkSocket(mat, nodes_data, node_data, expr, property, socket_mapping):
    link_node_exp = expr.value.node if expr.struct_type == 'ExpressionInput' else expr.value
    link_node_name = link_node_exp.object_name.FullName()
    if link_node_name in nodes_data:
        link_node_data = nodes_data[link_node_name]
        link_node_type = link_node_data.classname
        if link_node_type in class_blacklist: return
        
        node, link_node = (node_data.node, link_node_data.node)
        outputs = link_node_data.link_indirect if link_node_data.link_indirect else link_node.outputs
        src_socket = outputs[expr.value.node_output_i if expr.struct_type == 'ExpressionInput' else 0]
        dst_socket = None

        if property in socket_mapping: 
            if link_node_type == 'MaterialExpressionAppendVector' and node.bl_idname == 'ShaderNodeCombineXYZ': raise Exception("Unreal's append is annoying")
            dst_socket = node.inputs[socket_mapping[property]] # dst_index
        else: print(f"UNKNOWN PARAM: {node.name}.{property}")
        if node_data.input_remap and property in node_data.input_remap: dst_socket = node_data.input_remap[property]
        if src_socket and dst_socket:
            link = mat.node_tree.links.new(src_socket, dst_socket)
            if mute_fresnel and src_socket.node.bl_idname == 'ShaderNodeFresnel': link.is_muted = True
        else: print(f"FAILED LINK: {node.name}.{property}")
    else: print(f"MISSING NODE: {str(link_node_name)}")
def LinkSockets(mat, nodes_data, node_data):
    mapping = UE2BlenderNode_dict.get(node_data.classname)
    if mapping and mapping.inputs:
        for property in mapping.inputs:
            if property in node_data.export.properties:
                expr = node_data.export.properties[property]
                match expr.type:
                    case 'StructProperty': LinkSocket(mat, nodes_data, node_data, expr, property, mapping.inputs)
                    case 'ArrayProperty':
                        for i, elem in enumerate(expr.value): LinkSocket(mat, nodes_data, node_data, elem['Input'], i, { i:mapping.inputs[property][i] })
def ImportUMaterial(filepath, mat_name=None, mat_mesh=None): # TODO: return asset
    t0 = time.time()
    if logging: print(f"Import \"{filepath}\"")

    with UAsset(filepath, True) as asset:
        for exp in asset.exports:
            classname = exp.export_class_type
            params = exp.properties
            match classname:
                case 'Material': # TODO: can this not be first?
                    graph_data = GraphData() # TODO: replace with attributes on export?
                    nodes_data = graph_data.nodes_data

                    if not mat_name: mat_name = exp.object_name.FullName()
                    mat = bpy.data.materials.new(mat_name)
                    mat.use_nodes = True
                    node_tree = mat.node_tree
                    node = node_tree.nodes['Principled BSDF']
                    SetNodePos(node, 'EditorX', 'EditorY', params)
                    node_tree.nodes['Material Output'].location = node.location + Vector((300,0))
                    node_data = NodeData(exp, node=node)

                    for exr_exp in params.TryGetValue('Expressions', ()): CreateNode(exr_exp.value, mat, nodes_data, graph_data, mat_mesh)
                    for comment_exp in params.TryGetValue('EditorComments', ()):
                        comment_node = CreateNode(comment_exp.value, mat, nodes_data, graph_data, mat_mesh).node
                        for eval_node in filter(lambda n: not n.parent, node_tree.nodes):
                            diff = eval_node.location - comment_node.location
                            if diff.x > 0 and diff.x < comment_node.width and diff.y < 0 and diff.y > -comment_node.height: eval_node.parent = comment_node

                    match params.TryGetValue('BlendMode'):
                        case 'BLEND_Translucent':
                            mat.blend_method, mat.shadow_method = ('BLEND', 'HASHED')
                            node.inputs['Transmission'].default_value = 1
                        case 'BLEND_Masked':
                            mat.blend_method = mat.shadow_method = 'CLIP'
                        case _:
                            mat.blend_method = mat.shadow_method = 'OPAQUE'
                    mat.use_backface_culling = not params.TryGetValue('TwoSided', False)

                    if 'Normal' in params:
                        normal_map = node_tree.nodes.new('ShaderNodeNormalMap') # TODO: set normal uv
                        normal_map.location = node.location + Vector((-200, -570))
                        node_tree.links.new(normal_map.outputs['Normal'], node.inputs['Normal'])

                        n2rgb = node_tree.nodes.new('ShaderNodeGroup')
                        n2rgb.node_tree = bpy.data.node_groups['NormalToRGB']
                        n2rgb.location = normal_map.location + Vector((-160, -130))
                        n2rgb.hide = True
                        node_tree.links.new(n2rgb.outputs['RGB'], normal_map.inputs['Color'])

                        node_data.input_remap = { 'Normal':n2rgb.inputs['Normal'] }

                    for name in nodes_data: LinkSockets(mat, nodes_data, nodes_data[name]) # TODO: this iterates nodes without links!
                    LinkSockets(mat, nodes_data, node_data)
                    
                    ior = node.inputs['IOR']
                    if ior.is_linked: ior.links[0].is_muted = mute_ior
                case 'MaterialInstanceConstant':
                    mat_parent = params.TryGetValue('Parent')
                    #mat_parent_name = mat_parent.object_name.FullName()
                    mat_path = ArchiveToProjectPath(mat_parent.import_ref.object_name.FullName())
                    if not mat_name: mat_name = exp.object_name.FullName() # TODO: unify
                    mat, graph_data = ImportUMaterial(mat_path, mat_name, mat_mesh) # TODO: handle not found

                    for param in params.TryGetValue('ScalarParameterValues', ()):
                        node_data = graph_data.node_guids.get(param.value.TryGetValue('ExpressionGUID'))
                        if node_data: node_data.node.outputs[0].default_value = param.value.TryGetValue('ParameterValue')
                    for param in params.TryGetValue('VectorParameterValues', ()):
                        node_data = graph_data.node_guids.get(param.value.TryGetValue('ExpressionGUID'))
                        if node_data:
                            node, value = (node_data.node, param.value.TryGetValue('ParameterValue'))
                            node.inputs['RGB'].default_value = value.ToTuple()
                            node.inputs['A'].default_value = value.a
                    for param in params.TryGetValue('TextureParameterValues', ()):
                        tex_imp = param.value.TryGetValue('ParameterValue')
                        if tex_imp:
                            tex = TryGetExtractedImport(tex_imp, extract_dir) # TODO: reuse?
                            if tex:
                                node = graph_data.node_guids.get(param.value.TryGetValue('ExpressionGUID')).node
                                if node.image: tex.colorspace_settings.name = node.image.colorspace_settings.name
                                node.image = tex
                            else: print(f"Missing Texture \"{tex_imp.import_ref.object_name.str}\"")
    
    if logging: print(f"Imported {mat.name}: {(time.time() - t0) * 1000:.2f}ms")
    return (mat, graph_data)

if __name__ != "import_umat":
    importlib.reload(import_uasset)
    for mat in bpy.data.materials: bpy.data.materials.remove(mat)

    #filepath = r"F:\Art\Assets\Game\Blender UE4 Importer\Samples\M_Base_Trim.uasset"
    #filepath = r"F:\Art\Assets\Game\Blender UE4 Importer\Samples\MI_Trim_A_Red2.uasset"
    #filepath = r"C:\Users\jdeacutis\Desktop\fSpy\New folder\Blender-UE4-Importer\Samples\M_Base_Trim.uasset"
    ImportUMaterial(r"F:\Art\Assets\Game\Blender UE4 Importer\Samples\MI_Trim_A_Red2.uasset")
    print("Done")