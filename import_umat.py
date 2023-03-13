from __future__ import annotations
import bpy, sys, time, os, pathlib, subprocess, importlib
from struct import *
from mathutils import *

cur_dir = os.path.dirname(__file__)
if cur_dir not in sys.path: sys.path.append(cur_dir)
import import_uasset
from import_uasset import UAsset, Import, Export, Properties

umodel_path = cur_dir + r"\umodel.exe"
mute_ior = True
mute_fresnel = True

filepath = pathlib.Path(cur_dir) / "UE_nodes.blend"
node_tree_path = filepath / "NodeTree"
def TryAppendNodeGroups():
    if 'AdditiveSurface' not in bpy.data.node_groups:
        with bpy.data.libraries.load(str(filepath)) as (data_from, data_to):
            for node_group in data_from.node_groups:
                bpy.ops.wm.append(filepath=str(node_tree_path / node_group), directory=str(node_tree_path), filename=node_group)

def TryGetExtractedImport(imp:Import, extract_dir):
    if not hasattr(imp, "extracted"):
        archive_path = imp.import_ref.object_name
        extracted_path = os.path.normpath(extract_dir + archive_path + ".png")
        if not os.path.exists(extracted_path):
            asset_path = imp.asset.ToProjectPath(archive_path)
            extract_dir = os.path.join(extract_dir, "Game")
            subprocess.run(f"\"{umodel_path}\" -export -png -out=\"{extract_dir}\" \"{asset_path}\"")
        try:
            imp.extracted = tex = bpy.data.images.load(extracted_path, check_existing=True)

            tex_uasset_path = imp.asset.ToProjectPath(archive_path)
            with UAsset(tex_uasset_path, False) as asset:
                for export in asset.exports:
                    if export.export_class_type == 'Texture2D':
                        export.ReadProperties(False, False)
                        tex.colorspace_settings.name = 'sRGB' if export.properties.TryGetValue('SRGB',True) else 'Non-Color'
                        tex['flip_y'] = export.properties.TryGetValue('bFlipGreenChannel',False)
                        break
        except:
            imp.extracted = None
            pass
    return imp.extracted

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
        self.nodes_data:dict[str,NodeData] = {}
        self.node_guids = {}

def HandleTextureObject(expr:Import, nodes_data:dict[str,NodeData], node_data:NodeData):
    tex_param_node_exp = expr.value.node
    tex_imp = tex_param_node_exp.properties.TryGetValue('Texture')
    if tex_imp:
        node = node_data.node

        tex_param_node_data = nodes_data[tex_param_node_exp.object_name]
        tex_param_node_data.linked_tex_nodes = getattr(tex_param_node_data, 'linked_tex_nodes', [])
        tex_param_node_data.linked_tex_nodes.append(node)

        tex = TryGetExtractedImport(tex_imp, tex_imp.asset.extract_dir) # TODO: unify?
        if tex:
            if node.bl_idname == 'ShaderNodeTexImage': SetNodeTexture(node, tex)
        else: print(f"Missing Texture \"{tex_imp.import_ref.object_name}\"")

default_mapping = UE2BlenderNodeMapping('ShaderNodeMath', label="UNKNOWN", color=Color((1,0,0)))
UE2BlenderNode_dict = {
    'Material' : UE2BlenderNodeMapping('ShaderNodeBsdfPrincipled', hide=False, inputs={ 'BaseColor':'Base Color','Metallic':'Metallic','Specular':'Specular','Roughness':'Roughness',
                                       'EmissiveColor':'Emission','Opacity':'Alpha','OpacityMask':'Alpha','Normal':'Normal','Refraction':'IOR' }),
    'MaterialExpressionAdd'               : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='ADD', inputs={'A':0,'B':1}),
    'MaterialExpressionMultiply'          : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='MULTIPLY', inputs={'A':0,'B':1}),
    'MaterialExpressionConstant'          : UE2BlenderNodeMapping('ShaderNodeValue', hide=False),
    'MaterialExpressionScalarParameter'   : UE2BlenderNodeMapping('ShaderNodeValue', hide=False),
    'MaterialExpressionConstant3Vector'   : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='RGBA', hide=False, outputs={'RGB':0,'R':1,'G':2,'B':3,'A':4}),
    'MaterialExpressionVectorParameter'   : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='RGBA', hide=False, outputs={'RGB':0,'R':1,'G':2,'B':3,'A':4}),
    'MaterialExpressionStaticSwitchParameter' : UE2BlenderNodeMapping('ShaderNodeMixRGB', label="Switch", hide=False, inputs={'A':2,'B':1}),
    'MaterialExpressionAppendVector'      : UE2BlenderNodeMapping('ShaderNodeCombineXYZ', label="Append", inputs={'A':0,'B':1}),
    'MaterialExpressionLinearInterpolate' : UE2BlenderNodeMapping('ShaderNodeMixRGB', label="Lerp", inputs={'A':1,'B':2,'Alpha':0}),
    'MaterialExpressionClamp'             : UE2BlenderNodeMapping('ShaderNodeClamp', inputs={'Input':0,'Min':1,'Max':2}),
    'MaterialExpressionPower'             : UE2BlenderNodeMapping('ShaderNodeMath', subtype='POWER', inputs={'Base':0,'Exponent':1}),
    'MaterialExpressionTextureSample'     : UE2BlenderNodeMapping('ShaderNodeTexImage', hide=False, inputs={'Coordinates':0, 'TextureObject':HandleTextureObject}),
    'MaterialExpressionTextureSampleParameter2D' : UE2BlenderNodeMapping('ShaderNodeTexImage', hide=False, inputs={'Coordinates':0}),
    'MaterialExpressionTextureObjectParameter'   : UE2BlenderNodeMapping('ShaderNodeValue'),
    'MaterialExpressionTextureCoordinate' : UE2BlenderNodeMapping('ShaderNodeUVMap', hide=False),
    'MaterialExpressionDesaturation'      : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='Desaturation', inputs={'Input':0,'Fraction':1}),
    'MaterialExpressionComment'           : UE2BlenderNodeMapping('NodeFrame'),
    'MaterialExpressionFresnel'           : UE2BlenderNodeMapping('ShaderNodeFresnel', hide=False),
    'CheapContrast_RGB'                   : UE2BlenderNodeMapping('ShaderNodeBrightContrast', hide=False, inputs={'FunctionInputs':('Color','Contrast')}),
    'BlendAngleCorrectedNormals'          : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='BlendAngleCorrectedNormals', hide=False, inputs={'FunctionInputs':(0,1)}),
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
                rgb2n.node_tree = bpy.data.node_groups['RGBtoNormalY-']
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
def CreateNode(exp:Export, mat, nodes_data:dict[str,NodeData], graph_data, mesh):
    name = exp.object_name
    classname = exp.export_class_type # TODO: inline?
    nodes_data[name] = node_data = NodeData(exp)
    params = exp.properties

    if classname in class_blacklist: return None # TODO: iterate material expression array instead?

    if classname == 'MaterialExpressionMaterialFunctionCall': # TODO: import subtree from unreal directory
        classname = params.TryGetValue('MaterialFunction').object_name
    node_data.classname = classname

    mapping = UE2BlenderNode_dict.get(classname)
    if not mapping:
        print(f"UNKNOWN UMAT CLASS: {classname}")
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
                if mesh == None: mesh = bpy.context.object.data # TODO: less fragile?
                try: node.uv_map = mesh.uv_layers.keys()[uv_i]
                except:
                    print(f"Failed to use UV{uv_i} from mesh")
                    pass
        case 'MaterialExpressionTextureSampleParameter2D' | 'MaterialExpressionTextureSample':
            tex_imp = params.TryGetValue('Texture')
            if tex_imp:
                tex = TryGetExtractedImport(tex_imp, exp.asset.extract_dir)
                if tex:
                    SetNodeTexture(node, tex)
                    if params.TryGetValue('SamplerType') == 'SAMPLERTYPE_Normal': node.interpolation = 'Smart'
                else: print(f"Missing Texture \"{tex_imp.import_ref.object_name}\"")
    expr_guid = params.TryGetValue('ExpressionGUID')
    if expr_guid: graph_data.node_guids[expr_guid] = node_data
    return node_data
def LinkSocket(mat, nodes_data:dict[str,NodeData], node_data:NodeData, expr:Import, property, dst_index):
    link_node_exp = expr.value.node if expr.struct_type == 'ExpressionInput' else expr.value
    link_node_data = nodes_data.get(link_node_exp.object_name)
    if link_node_data:
        link_node_type = link_node_data.classname
        if link_node_type in class_blacklist: return
        
        node, link_node = (node_data.node, link_node_data.node)
        outputs = link_node_data.link_indirect if link_node_data.link_indirect else link_node.outputs
        src_socket = outputs[expr.value.node_output_i if expr.struct_type == 'ExpressionInput' else 0]
        dst_socket = None

        if link_node_type == 'MaterialExpressionAppendVector' and node.bl_idname == 'ShaderNodeCombineXYZ': raise Exception("Unreal's append is annoying")
        dst_socket = node.inputs[dst_index]
        if node_data.input_remap and property in node_data.input_remap: dst_socket = node_data.input_remap[property]
        if src_socket and dst_socket:
            link = mat.node_tree.links.new(src_socket, dst_socket)
            if mute_fresnel and src_socket.node.bl_idname == 'ShaderNodeFresnel': link.is_muted = True
        else: print(f"FAILED LINK: {node.name}.{property}")
    else: print(f"Link Failed, Missing Node: {str(link_node_exp.object_name)}")
def LinkSockets(mat, nodes_data:dict[str,NodeData], node_data:NodeData):
    mapping = UE2BlenderNode_dict.get(node_data.classname)
    if mapping and mapping.inputs:
        for property, map_val in mapping.inputs.items():
            expr = node_data.export.properties.get(property)
            if expr:
                if callable(map_val): map_val(expr, nodes_data, node_data)
                else:
                    match expr.type:
                        case 'StructProperty': LinkSocket(mat, nodes_data, node_data, expr, property, map_val)
                        case 'ArrayProperty':
                            for i, elem in enumerate(expr.value): LinkSocket(mat, nodes_data, node_data, elem['Input'], i, map_val[i])
def SetNodeTexture(node, image):
    node.image = image
    links = node.outputs['Color'].links
    if len(links) > 0:
        linked_node = links[0].to_node
        if linked_node.node_tree.name.startswith('RGBtoNormal'):
            linked_node.node_tree = bpy.data.node_groups['RGBtoNormal' if image.get('flip_y', False) else 'RGBtoNormalY-']
def ImportUMaterial(filepath, mat_name=None, mesh=None, log=False): # TODO: return asset
    t0 = time.time()
    if not os.path.exists(filepath):
        print(f"Error: \"{filepath}\" Does Not Exist!")
        return (None, None)
    TryAppendNodeGroups()
    with UAsset(filepath, True) as asset:
        for exp in asset.exports:
            classname = exp.export_class_type
            params = exp.properties
            match classname:
                case 'Material': # TODO: can this not be first?
                    graph_data = GraphData() # TODO: replace with attributes on export?
                    nodes_data = graph_data.nodes_data

                    if not mat_name: mat_name = exp.object_name
                    mat = bpy.data.materials.new(mat_name)
                    mat.use_nodes = True
                    mat["UAsset"] = asset.f.byte_stream.name
                    node_tree = mat.node_tree
                    node = node_tree.nodes['Principled BSDF']
                    SetNodePos(node, 'EditorX', 'EditorY', params)
                    node_tree.nodes['Material Output'].location = node.location + Vector((300,0))
                    node_data = NodeData(exp, node=node)

                    for exr_exp in params.TryGetValue('Expressions', ()): CreateNode(exr_exp.value, mat, nodes_data, graph_data, mesh)
                    for comment_exp in params.TryGetValue('EditorComments', ()):
                        comment_node = CreateNode(comment_exp.value, mat, nodes_data, graph_data, mesh).node
                        for eval_node in filter(lambda n: not n.parent, node_tree.nodes):
                            diff = eval_node.location - comment_node.location
                            if diff.x > 0 and diff.x < comment_node.width and diff.y < 0 and diff.y > -comment_node.height: eval_node.parent = comment_node

                    match params.TryGetValue('BlendMode'):
                        case 'BLEND_Translucent':
                            mat.blend_method, mat.shadow_method = ('BLEND', 'HASHED')
                            node.inputs['Transmission'].default_value = 1
                        case 'BLEND_Masked':
                            mat.blend_method = mat.shadow_method = 'CLIP'
                        case 'BLEND_Additive':
                            mat.blend_method, mat.shadow_method = ('BLEND', 'NONE')

                            additive = node_tree.nodes.new('ShaderNodeGroup')
                            additive.node_tree = bpy.data.node_groups['AdditiveSurface']
                            additive.location = node.location + Vector((0, 150))
                            node_tree.links.new(additive.outputs[0], node_tree.nodes['Material Output'].inputs['Surface'])
                            node_data.input_remap = { 'EmissiveColor':additive.inputs['Emission'] }
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

                    for name in nodes_data:
                        LinkSockets(mat, nodes_data, nodes_data[name]) # TODO: this iterates nodes without links!
                    LinkSockets(mat, nodes_data, node_data)
                    
                    ior = node.inputs['IOR']
                    if ior.is_linked: ior.links[0].is_muted = mute_ior
                case 'MaterialInstanceConstant':
                    mat_parent = params.TryGetValue('Parent')
                    mat_path = asset.ToProjectPath(mat_parent.import_ref.object_name)
                    if not mat_name: mat_name = exp.object_name # TODO: unify
                    mat, graph_data = ImportUMaterial(mat_path, mat_name, mesh) # TODO: handle not found

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
                            tex = TryGetExtractedImport(tex_imp, tex_imp.asset.extract_dir) # TODO: reuse?
                            if tex:
                                tex_node_data = graph_data.node_guids[param.value.TryGetValue('ExpressionGUID')]
                                tex_node = tex_node_data.node
                                if tex_node.bl_idname == 'ShaderNodeTexImage': SetNodeTexture(tex_node, tex)
                                else:
                                    for tex_node in tex_node_data.linked_tex_nodes: SetNodeTexture(tex_node, tex)

                            else: print(f"Missing Texture \"{tex_imp.import_ref.object_name}\"")
    
    if log: print(f"Imported {mat.name}: {(time.time() - t0) * 1000:.2f}ms")
    return (mat, graph_data)
def TryGetUMaterialImport(mat_imp:Import, mesh):
    mat = bpy.data.materials.get(mat_imp.object_name)
    if not mat:
        umat_path = mat_imp.asset.ToProjectPath(mat_imp.import_ref.object_name)
        try: mat, graph_data = ImportUMaterial(umat_path, mesh=mesh)
        except Exception as e:
            print(f"Failed to Import {mat_imp.object_name}: {e}")
            pass
    return mat

if __name__ != "import_umat":
    importlib.reload(import_uasset)
    for mat in bpy.data.materials: bpy.data.materials.remove(mat)

    #filepath = r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Materials\M_Base_Trim.uasset"
    filepath = r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Materials\MI_Trim_A_Red2.uasset"
    ImportUMaterial(filepath)
    print("Done")