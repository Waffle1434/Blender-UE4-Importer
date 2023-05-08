from __future__ import annotations
import bpy, sys, time, os, pathlib, subprocess, importlib
from struct import *
from mathutils import *
from bpy.props import *
from bpy_extras.io_utils import ImportHelper

cur_dir = os.path.dirname(__file__)
if cur_dir not in sys.path: sys.path.append(cur_dir)
import uasset, register_helper
from uasset import UAsset, Import, Export, Properties, UProperty

umodel_path = cur_dir + r"\umodel.exe"
mute_ior = True
mute_fresnel = True

blend_filepath = pathlib.Path(cur_dir) / "UE_nodes.blend"
node_tree_path = blend_filepath / "NodeTree"
def TryAppendNodeGroups():
    if 'AdditiveSurface' not in bpy.data.node_groups:
        with bpy.data.libraries.load(str(blend_filepath)) as (data_from, data_to):
            for node_group in data_from.node_groups:
                bpy.ops.wm.append(filepath=str(node_tree_path / node_group), directory=str(node_tree_path), filename=node_group, set_fake=True)

def TryGetExtractedImport(imp:Import, extract_dir):
    if not hasattr(imp, "extracted"):
        archive_path = imp.import_ref.object_name
        extracted_path = os.path.normpath(extract_dir + archive_path + ".png")
        if not os.path.exists(extracted_path):
            asset_path = imp.asset.ToProjectPath(archive_path)
            extract_dir = os.path.join(extract_dir, "Engine" if archive_path.startswith("/Engine/") else "Game")
            print(f"Extracting {asset_path}")
            subprocess.run(f"\"{umodel_path}\" -export -png -out=\"{extract_dir}\" \"{asset_path}\"")
        try:
            imp.extracted = tex = bpy.data.images.load(extracted_path, check_existing=True)

            tex_uasset_path = imp.asset.ToProjectPath(archive_path)
            with UAsset(tex_uasset_path, uproject=imp.asset.uproject) as asset:
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
    def __init__(self, bl_idname, subtype=None, label=None, hide=True, inputs=None, constants=None, defaults=None, outputs=None, color=None, width=100, visible_outputs=None):
        self.bl_idname = bl_idname
        self.subtype = subtype
        self.label = label
        self.hide = hide
        self.inputs = inputs
        self.constants = constants
        self.defaults = defaults
        self.outputs = outputs
        self.color = color
        self.width = width
        self.visible_outputs = visible_outputs
class NodeData():
    def __init__(self, export:Export, classname=None, node=None, link_indirect=None, input_remap=None):
        self.export = export
        self.classname = classname if classname else export.export_class_type
        self.node = node
        self.link_indirect = link_indirect
        self.input_remap = input_remap
class GraphData(): # TODO: redundant, only returned node_guids used
    def __init__(self):
        self.nodes_data:dict[str,NodeData] = {}
        self.node_guids = {}
        self.param_nodes = {}

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
    'Material' : UE2BlenderNodeMapping('ShaderNodeBsdfPrincipled', hide=False, width=None, inputs={ 'BaseColor':'Base Color','Metallic':'Metallic','Specular':'Specular','Roughness':'Roughness',
                                       'EmissiveColor':'Emission','Opacity':'Alpha','OpacityMask':'Alpha','Normal':'Normal','Refraction':'IOR' }, defaults={'BaseColor':0}),
    'MaterialExpressionAdd'               : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='ADD', inputs={'A':0,'B':1}, defaults={'A':0,'B':1}),
    'MaterialExpressionSubtract'          : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='SUBTRACT', inputs={'A':0,'B':1}, defaults={'A':0,'B':1}),
    'MaterialExpressionMultiply'          : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='MULTIPLY', inputs={'A':0,'B':1}, defaults={'A':0,'B':1}),
    'MaterialExpressionDivide'            : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='DIVIDE', inputs={'A':0,'B':1}, defaults={'A':1,'B':2}),
    'MaterialExpressionPower'             : UE2BlenderNodeMapping('ShaderNodeMath', subtype='POWER', inputs={'Base':0,'Exponent':1}, defaults={'Exponent':2}),
    'MaterialExpressionLogarithm2'        : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='Log', inputs={'X':0}, constants={'Base':('Base',2)}, label="Log2"),
    'MaterialExpressionLogarithm10'       : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='Log', inputs={'X':0}, constants={'Base':('Base',10)}, label="Log10"),
    'MaterialExpressionAbs'               : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='ABSOLUTE', inputs={'Input':0}),
    'MaterialExpressionFrac'              : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='FRACTION', inputs={'Input':0}),
    'MaterialExpressionFmod'              : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='MODULO', inputs={'A':0,'B':1}),
    'MaterialExpressionCeil'              : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='CEIL', inputs={'Input':0}),
    'MaterialExpressionFloor'             : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='FLOOR', inputs={'Input':0}),
    'MaterialExpressionRound'             : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='Round', inputs={'Input':0}),
    'MaterialExpressionTruncate'          : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='Truncate', inputs={'Input':0}),
    'MaterialExpressionSign'              : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='Sign', inputs={'Input':0}),
    'MaterialExpressionOneMinus'          : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='SUBTRACT', inputs={'A':0,'Input':1}, defaults={'A':1}, label="1-x"),
    'MaterialExpressionMin'               : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='MINIMUM', inputs={'A':0,'B':1}, defaults={'A':0,'B':1}),
    'MaterialExpressionMax'               : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='MAXIMUM', inputs={'A':0,'B':1}, defaults={'A':0,'B':1}),
    'MaterialExpressionStep'              : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='Step', inputs={'Y':0,'X':1}, defaults={'Y':0,'X':1}),
    'MaterialExpressionSmoothStep'        : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='SmoothStep', inputs={'Min':0,'Max':1,'Value':2}, defaults={'Min':0,'Max':1,'Value':0}, width=120),
    'MaterialExpressionClamp'             : UE2BlenderNodeMapping('ShaderNodeClamp', inputs={'Input':0,'Min':1,'Max':2}),

    'MaterialExpressionDistance'          : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='DISTANCE', inputs={'A':0,'B':1}),
    'MaterialExpressionDotProduct'        : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='DOT_PRODUCT', inputs={'A':0,'B':1}, label="Dot"),
    'MaterialExpressionCrossProduct'      : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='CROSS_PRODUCT', inputs={'A':0,'B':1}, label="Cross"),
    'MaterialExpressionNormalize'         : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='NORMALIZE', inputs={'VectorInput':0}),

    'MaterialExpressionSine'              : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='Sine', inputs={'Input':0}, constants={'Period':('Period',1)}, hide=False),
    'MaterialExpressionCosine'            : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='Cosine', inputs={'Input':0}, constants={'Period':('Period',1)}, hide=False),
    'MaterialExpressionTangent'           : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='Tangent', inputs={'Input':0}, constants={'Period':('Period',1)}, hide=False),
    'MaterialExpressionArcsine'           : UE2BlenderNodeMapping('ShaderNodeMath', subtype='ARCSINE', inputs={'Input':0}),
    'MaterialExpressionArccosine'         : UE2BlenderNodeMapping('ShaderNodeMath', subtype='ARCCOSINE', inputs={'Input':0}),
    'MaterialExpressionArctangent'        : UE2BlenderNodeMapping('ShaderNodeMath', subtype='ARCTANGENT', inputs={'Input':0}),
    'MaterialExpressionArcsineFast'       : UE2BlenderNodeMapping('ShaderNodeMath', subtype='ARCSINE', inputs={'Input':0}),
    'MaterialExpressionArccosineFast'     : UE2BlenderNodeMapping('ShaderNodeMath', subtype='ARCCOSINE', inputs={'Input':0}),
    'MaterialExpressionArctangentFast'    : UE2BlenderNodeMapping('ShaderNodeMath', subtype='ARCTANGENT', inputs={'Input':0}),

    'MaterialExpressionStaticBool'        : UE2BlenderNodeMapping('ShaderNodeValue', hide=False),
    'MaterialExpressionScalarParameter'   : UE2BlenderNodeMapping('ShaderNodeValue', hide=False),
    'MaterialExpressionConstant'          : UE2BlenderNodeMapping('ShaderNodeValue', hide=False),
    'MaterialExpressionConstant2Vector'   : UE2BlenderNodeMapping('ShaderNodeCombineXYZ', hide=False),
    'MaterialExpressionConstant3Vector'   : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='Const3', hide=False, width=None),
    'MaterialExpressionConstant4Vector'   : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='RGBA', hide=False, width=None), #outputs={'R':1,'G':2,'B':3,'A':4}
    'MaterialExpressionVectorParameter'   : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='RGBA', hide=False, width=None, outputs={'RGB':0,'R':1,'G':2,'B':3,'A':4}),
    'MaterialExpressionStaticSwitch'      : UE2BlenderNodeMapping('ShaderNodeMixRGB', label="Switch", hide=False, inputs={'A':2,'B':1,'Value':0}),
    'MaterialExpressionStaticSwitchParameter' : UE2BlenderNodeMapping('ShaderNodeMixRGB', label="Switch", hide=False, inputs={'A':2,'B':1}),
    'MaterialExpressionTextureSample'     : UE2BlenderNodeMapping('ShaderNodeTexImage', hide=False, width=None, inputs={'Coordinates':0, 'TextureObject':HandleTextureObject}),
    'MaterialExpressionTextureSampleParameter2D' : UE2BlenderNodeMapping('ShaderNodeTexImage', hide=False, width=None, inputs={'Coordinates':0}),
    'MaterialExpressionTextureObjectParameter'   : UE2BlenderNodeMapping('ShaderNodeValue'),
    'MaterialExpressionTextureCoordinate' : UE2BlenderNodeMapping('ShaderNodeUVMap', hide=False, width=None),
    'MaterialExpressionIf'                : UE2BlenderNodeMapping('ShaderNodeGroup', subtype="If", hide=False, 
                                                                  inputs={'A':0,'B':1,'AGreaterThanB':3,'AEqualsB':4,'ALessThanB':5}, defaults={'B':0}, constants={'EqualsThreshold':(2,0.00001)}),
    'MaterialExpressionAppendVector'      : UE2BlenderNodeMapping('ShaderNodeCombineXYZ', label="Append", inputs={'A':0,'B':1}),
    'MaterialExpressionComponentMask'     : UE2BlenderNodeMapping('ShaderNodeSeparateXYZ', label="Mask", inputs={'Input':0}),
    'MaterialExpressionLinearInterpolate' : UE2BlenderNodeMapping('ShaderNodeMixRGB', label="Lerp", inputs={'A':1,'B':2,'Alpha':0}, defaults={'A':0,'B':1,'Alpha':0.5}), # constants={'A':(1,0), 'B':(2,1), 'Alpha':(0,0)}
    'MaterialExpressionTwoSidedSign'      : UE2BlenderNodeMapping('ShaderNodeGroup', subtype="TwoSidedSign", hide=False, width=140),
    'MaterialExpressionVertexColor'       : UE2BlenderNodeMapping('ShaderNodeVertexColor', hide=False, label="Vertex Color"),
    'MaterialExpressionVertexNormalWS'    : UE2BlenderNodeMapping('ShaderNodeNewGeometry', hide=False, label="Vertex Normal", visible_outputs=('Normal',), outputs={'Normal':'Normal'}),
    'MaterialExpressionWorldPosition'     : UE2BlenderNodeMapping('ShaderNodeNewGeometry', hide=False, width=170, label="Absolute World Position", visible_outputs=('Position',)),
    'MaterialExpressionObjectPositionWS'  : UE2BlenderNodeMapping('ShaderNodeObjectInfo', hide=False, width=None, label="Object Position", visible_outputs=('Location',)),
    'MaterialExpressionCameraPositionWS'  : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='CameraPosition', hide=False, width=None),
    'MaterialExpressionCameraVectorWS'    : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='CameraVector', hide=False, width=None),
    'MaterialExpressionScreenPosition'    : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='ScreenPosition', hide=False, width=None),
    'MaterialExpressionPixelDepth'        : UE2BlenderNodeMapping('ShaderNodeCameraData', hide=False, width=None, visible_outputs=('View Z Depth',)),

    'MaterialExpressionDesaturation'      : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='Desaturation', inputs={'Input':0,'Fraction':1}),
    'MaterialExpressionComment'           : UE2BlenderNodeMapping('NodeFrame', width=None),
    'MaterialExpressionReroute'           : UE2BlenderNodeMapping('NodeReroute', hide=False, width=None, inputs={'Input':0}),
    'MaterialExpressionFresnel'           : UE2BlenderNodeMapping('ShaderNodeFresnel', hide=False),
    'MaterialExpressionBlackBody'         : UE2BlenderNodeMapping('ShaderNodeBlackbody', hide=False, inputs={'Temp':0}),
    'CheapContrast_RGB'                   : UE2BlenderNodeMapping('ShaderNodeBrightContrast', width=None, hide=False, inputs={'FunctionInputs':('Color','Contrast')}),
    'BlendAngleCorrectedNormals'          : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='BlendAngleCorrectedNormals', width=None, hide=False, inputs={'FunctionInputs':(0,1)}),
    'CameraDepthFade'                     : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='CameraDepthFade', width=None, hide=False, inputs={'FunctionInputs':(0,1,2)}),
    'MaterialExpressionFunctionInput'     : UE2BlenderNodeMapping('NodeReroute', hide=False, width=None),
    'MaterialExpressionFunctionOutput'    : UE2BlenderNodeMapping('NodeReroute', hide=False, width=None, inputs={'A':0}),
}
ue_to_bl_type = { 'FunctionInput_Scalar':'NodeSocketFloat', 'FunctionInput_StaticBool':'NodeSocketFloat' }
class_blacklist = { 'SceneThumbnailInfoWithPrimitive', 'MetaData', 'MaterialExpressionPanner' }
material_classes = { 'Material', 'MaterialInstanceConstant' }
node_whitelist = { 'ShaderNodeBsdfPrincipled', 'ShaderNodeOutputMaterial' }

def DeDuplicateName(name):
    i = name.rfind('.')
    return name[:i] if i >= 0 else name
def GuessBaseDir(filename): return filename[:filename.find("Game")] # Unreal defaults to starting path with "Game" on asset export
def SetupNode(node_tree, name, mapping:UE2BlenderNodeMapping, node_data) -> bpy.types.ShaderNode: # TODO: inline
    node = node_tree.nodes.new(mapping.bl_idname)
    node.name = name
    node.hide = mapping.hide
    SetNodePos(node, node_data.export.properties)
    if mapping.subtype:
        if mapping.bl_idname == 'ShaderNodeGroup': node.node_tree = bpy.data.node_groups[mapping.subtype]
        else: node.operation = mapping.subtype
    if mapping.label: node.label = mapping.label
    node.use_custom_color = mapping.color != None
    if mapping.color: node.color = mapping.color
    if mapping.visible_outputs:
        for out_socket in node.outputs:
            if out_socket.name not in mapping.visible_outputs: out_socket.hide = True

    match mapping.bl_idname:
        case 'ShaderNodeTexImage' | 'ShaderNodeVertexColor':
            rgb_in = node.outputs['Color']
            if node_data.export.properties.TryGetValue('SamplerType') == 'SAMPLERTYPE_Normal':
                rgb2n = node_tree.nodes.new('ShaderNodeGroup')
                rgb2n.node_tree = bpy.data.node_groups['RGBtoNormalY-']
                rgb2n.hide = True
                SetNodePos(rgb2n, node_data.export.properties)
                rgb2n.location += Vector((0,30))
                node_tree.links.new(node.outputs['Color'], rgb2n.inputs['RGB'])
                rgb_in = rgb2n.outputs['Normal']

            rgba:bpy.types.ShaderNode = node_tree.nodes.new('ShaderNodeGroup')
            rgba.node_tree = bpy.data.node_groups['RGBA']
            rgba.hide, rgba.width,rgba.show_options  = (True, 100, False)
            rgba.location = node.location + Vector((160,-32))
            node_tree.links.new(rgb_in, rgba.inputs['RGB'])
            node_tree.links.new(node.outputs['Alpha'], rgba.inputs['A'])
            node_data.link_indirect = rgba.outputs
        case 'ShaderNodeMixRGB':
            node.inputs['Fac'].default_value = 0
    return node
def SetNodePos(node, params:Properties, param_x='MaterialExpressionEditorX', param_y='MaterialExpressionEditorY'): node.location = (params.TryGetValue(param_x,0), -params.TryGetValue(param_y,0))
def HandleDefaultConstants(mapping, node, params):
    if mapping.defaults:
        for ue_name, default_value in mapping.defaults.items():
            const_name = f'Const{ue_name}'
            if ue_name not in params: # or const_name in params:
                value = params.TryGetValue(const_name, default_value)
                socket = node.inputs[mapping.inputs[ue_name]]
                match socket.type:
                    case 'VECTOR': socket.default_value = (value, value, value)
                    case 'RGBA':   socket.default_value = (value, value, value, 1)
                    case _:        socket.default_value = value

def CreateNode(exp:Export, node_tree, nodes_data:dict[str,NodeData], graph_data, mesh=None):
    name = exp.object_name
    classname = exp.export_class_type # TODO: inline?
    nodes_data[name] = node_data = NodeData(exp)
    params = exp.properties

    if classname in class_blacklist: return None # TODO: iterate material expression array instead?

    if classname == 'MaterialExpressionMaterialFunctionCall': # TODO: import subtree from unreal directory
        matfnc_imp = params.TryGetValue('MaterialFunction')
        classname = matfnc_imp.object_name
        if classname not in UE2BlenderNode_dict:
            matfnc_subtype = ImportMaterialFunction(matfnc_imp)
            input_count = len(bpy.data.node_groups[matfnc_subtype].inputs)
            if input_count > 0:
                inputs = []
                for i in range(input_count): inputs.append(i)
                inputs = { 'FunctionInputs':tuple(inputs) }
            else: inputs = None
            UE2BlenderNode_dict[classname] = UE2BlenderNodeMapping('ShaderNodeGroup', matfnc_subtype, hide=False, inputs=inputs)
    node_data.classname = classname

    mapping = UE2BlenderNode_dict.get(classname)
    if not mapping:
        print(f"UNKNOWN UMAT CLASS: {classname}")
        mapping = default_mapping
    
    node_data.node = node = SetupNode(node_tree, name, mapping, node_data)

    sx, sy = (params.TryGetValue('SizeX'), params.TryGetValue('SizeY'))
    if sx != None: node.width = sx
    elif mapping.width: node.width = mapping.width
    if sy != None: node.height = sy
    txt, param_name = (params.TryGetValue('Text'), params.TryGetValue('ParameterName'))
    if txt: node.label = txt
    elif param_name:
        node.label = param_name
        node.width = max(node.width, 25 + 7*len(param_name))
    if param_name:
        param_nodes = graph_data.param_nodes.get(param_name)
        if not param_nodes: graph_data.param_nodes[param_name] = param_nodes = []
        param_nodes.append(node_data)

    HandleDefaultConstants(mapping, node, params)
    if mapping.constants:
        for ue_name, const in mapping.constants.items():
            bl_name, const_default = const
            const_val = params.TryGetValue(ue_name, const_default)
            node.inputs[bl_name].default_value = const_val

    if mapping.bl_idname == 'ShaderNodeGroup': node.show_options = False

    value = params.TryGetValue('DefaultValue')
    if value == None: value = params.TryGetValue('Constant')
    if value != None: # TODO: move to mapping class?
        match classname:
            case 'MaterialExpressionScalarParameter':
                node.outputs[0].default_value = value
            case 'MaterialExpressionConstant3Vector':
                node.inputs[0].default_value = value.ToTupleRGB()
            case 'MaterialExpressionVectorParameter':
                node.inputs['RGB'].default_value = value.ToTuple()
                node.inputs['A'].default_value = value.a
            case 'MaterialExpressionStaticSwitchParameter':
                node.inputs['Fac'].default_value = 1 if value else 0
    else:
        match classname:
            case 'MaterialExpressionConstant':
                r = params.TryGetValue('R', 0)
                node.outputs[0].default_value = r
            case 'MaterialExpressionConstant2Vector':
                r = params.TryGetValue('R', 0)
                g = params.TryGetValue('G', 0)
                node.inputs[0].default_value = r
                node.inputs[1].default_value = g
                node.inputs[2].hide = True
    match classname:
        case 'MaterialExpressionTextureCoordinate':
            uv_i = params.TryGetValue('CoordinateIndex')
            if uv_i != None:
                if mesh == None: node.uv_map = f"UV{uv_i}"
                else:
                    try: node.uv_map = mesh.uv_layers.keys()[uv_i]
                    except:
                        print(f"Failed to use UV{uv_i} from mesh")
                        pass
            tiling = (params.TryGetValue('UTiling', 1), params.TryGetValue('VTiling', 1))
            if tiling[0] != 1 or tiling[1] != 1:
                mult:bpy.types.ShaderNode = node_tree.nodes.new('ShaderNodeVectorMath')
                mult.operation = 'MULTIPLY'
                mult.inputs[1].default_value = (tiling[0], tiling[1], 0)
                mult.width = 100
                mult.location = node.location + Vector((160,-32))
                node_tree.links.new(node.outputs[0], mult.inputs[0])
                node_data.link_indirect = mult.outputs
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
def LinkSocket(node_tree, nodes_data:dict[str,NodeData], node_data:NodeData, expr:UProperty, property:str, dst_index):
    link_node_exp = expr.value.node if expr.struct_type == 'ExpressionInput' else expr.value
    link_node_data = nodes_data.get(link_node_exp.object_name)
    if link_node_data:
        link_node_type = link_node_data.classname
        if link_node_type in class_blacklist: return
        
        node, link_node = (node_data.node, link_node_data.node)
        outputs = link_node_data.link_indirect if link_node_data.link_indirect else link_node.outputs

        src_i = expr.value.node_output_i if expr.struct_type == 'ExpressionInput' else 0
        src_socket = outputs[src_i]
        while src_socket.hide or src_socket.is_unavailable: # TODO: this is awful
            src_i += 1
            src_socket = outputs[src_i]

        if link_node_type == 'MaterialExpressionAppendVector' and node.bl_idname == 'ShaderNodeCombineXYZ': raise Exception("Unreal's append is annoying")
        dst_socket = node.inputs[dst_index]
        if node_data.input_remap and property in node_data.input_remap: dst_socket = node_data.input_remap[property]
        if src_socket and dst_socket:
            link = node_tree.links.new(src_socket, dst_socket)
            if mute_fresnel and src_socket.node.bl_idname == 'ShaderNodeFresnel': link.is_muted = True
        else: print(f"FAILED LINK: {node.name}.{property}")
    else: print(f"Link Failed, Missing Node: \"{expr.value}\" {str(link_node_exp.object_name)} (\"{os.path.basename(node_data.export.asset.filepath)}\")")
def LinkSockets(node_tree, nodes_data:dict[str,NodeData], node_data:NodeData):
    mapping = UE2BlenderNode_dict.get(node_data.classname)
    if mapping and mapping.inputs:
        for property, map_val in mapping.inputs.items():
            expr = node_data.export.properties.get(property)
            if expr:
                if callable(map_val): map_val(expr, nodes_data, node_data)
                else:
                    match expr.type:
                        case 'StructProperty': LinkSocket(node_tree, nodes_data, node_data, expr, property, map_val)
                        case 'ArrayProperty':
                            for i, elem in enumerate(expr.value): LinkSocket(node_tree, nodes_data, node_data, elem['Input'], i, map_val[i])
def SetNodeTexture(node, image):
    node.image = image
    links = node.outputs['Color'].links
    if len(links) > 0:
        linked_node = links[0].to_node
        if linked_node.node_tree.name.startswith('RGBtoNormal'):
            linked_node.node_tree = bpy.data.node_groups['RGBtoNormal' if image.get('flip_y', False) else 'RGBtoNormalY-']
def ImportMaterialFunction(mat_fnc_imp:Import, mesh=None):
    node_graph_name = mat_fnc_imp.object_name
    if node_graph_name not in bpy.data.node_groups: ImportNodeGraph(mat_fnc_imp.asset.ToProjectPath(mat_fnc_imp.import_ref.object_name), mat_fnc_imp.asset.uproject, mesh=mesh)
    return node_graph_name
def ImportNodeGraph(filepath, uproject=None, name=None, mesh=None, log=False): # TODO: return asset?
    t0 = time.time()
    if not os.path.exists(filepath):
        print(f"Error: \"{filepath}\" Does Not Exist!")
        return (None, None)
    TryAppendNodeGroups()
    out = None
    with UAsset(filepath, True, uproject) as asset:
        for exp in asset.exports:
            classname = exp.export_class_type
            params = exp.properties
            match classname:
                case 'Material': # TODO: can this not be first?
                    graph_data = GraphData() # TODO: replace with attributes on export?
                    nodes_data = graph_data.nodes_data

                    if not name: name = exp.object_name
                    out = mat = bpy.data.materials.new(name)
                    mat.use_nodes = True
                    mat["UAsset"] = asset.f.byte_stream.name
                    node_tree = mat.node_tree
                    node = node_tree.nodes['Principled BSDF']
                    SetNodePos(node, params, 'EditorX', 'EditorY')
                    HandleDefaultConstants(UE2BlenderNode_dict['Material'], node, params)
                    node_tree.nodes['Material Output'].location = node.location + Vector((300,0))
                    node_data = NodeData(exp, node=node)

                    for exr_exp in params.TryGetValue('Expressions', ()): CreateNode(exr_exp.value, node_tree, nodes_data, graph_data, mesh)
                    for comment_exp in params.TryGetValue('EditorComments', ()):
                        comment_node = CreateNode(comment_exp.value, node_tree, nodes_data, graph_data, mesh).node
                        for eval_node in filter(lambda n: not n.parent, node_tree.nodes):
                            diff = eval_node.location - comment_node.location
                            if diff.x > 0 and diff.x < comment_node.width and diff.y < 0 and diff.y > -comment_node.height: eval_node.parent = comment_node

                    if params.TryGetValue('ShadingModel', '') == 'MSM_Unlit':
                        emission = node_tree.nodes.new('ShaderNodeEmission')
                        emission.location = node.location + Vector((0, 150))
                        node_tree.links.new(emission.outputs[0], node_tree.nodes['Material Output'].inputs['Surface'])
                        node_data.input_remap = { 'EmissiveColor':emission.inputs['Color'] }

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
                        LinkSockets(node_tree, nodes_data, nodes_data[name]) # TODO: this iterates nodes without links!
                    LinkSockets(node_tree, nodes_data, node_data)
                    
                    ior = node.inputs['IOR']
                    if ior.is_linked: ior.links[0].is_muted = mute_ior
                case 'MaterialInstanceConstant':
                    mat_parent = params.TryGetValue('Parent')
                    mat_path = asset.ToProjectPath(mat_parent.import_ref.object_name)
                    if not name: name = exp.object_name # TODO: unify
                    mat, graph_data = ImportNodeGraph(mat_path, uproject, name, mesh) # TODO: handle not found
                    out = mat

                    for param in params.TryGetValue('ScalarParameterValues', ()):
                        for node_data in graph_data.param_nodes.get(param.value.TryGetValue('ParameterName'), []):
                            node_data.node.outputs[0].default_value = param.value.TryGetValue('ParameterValue')
                    for param in params.TryGetValue('VectorParameterValues', ()):
                        for node_data in graph_data.param_nodes.get(param.value.TryGetValue('ParameterName'), []):
                            node, value = (node_data.node, param.value.TryGetValue('ParameterValue'))
                            node.inputs['RGB'].default_value = value.ToTuple()
                            node.inputs['A'].default_value = value.a
                    for param in params.TryGetValue('TextureParameterValues', ()):
                        tex_imp = param.value.TryGetValue('ParameterValue')
                        if tex_imp:
                            tex = TryGetExtractedImport(tex_imp, tex_imp.asset.extract_dir) # TODO: reuse?
                            if tex:
                                for tex_node_data in graph_data.param_nodes.get(param.value.TryGetValue('ParameterName'), []):
                                    tex_node = tex_node_data.node
                                    if tex_node.bl_idname == 'ShaderNodeTexImage': SetNodeTexture(tex_node, tex)
                                    else:
                                        for tex_node in tex_node_data.linked_tex_nodes: SetNodeTexture(tex_node, tex)
                            else: print(f"Missing Texture \"{tex_imp.import_ref.object_name}\"")
                case 'MaterialFunction': # TODO: very similar to Material, merge?
                    out = node_tree = bpy.data.node_groups.new(exp.object_name, 'ShaderNodeTree')
                    graph_data = GraphData() # TODO: replace with attributes on export?
                    nodes_data = graph_data.nodes_data

                    in_node = node_tree.nodes.new('NodeGroupInput')
                    out_node = node_tree.nodes.new('NodeGroupOutput')

                    input_positions = []
                    output_positions = []
                    
                    for exr_exp in params.TryGetValue('FunctionExpressions', ()):
                        node_data = CreateNode(exr_exp.value, node_tree, nodes_data, graph_data, None)
                        if node_data:
                            props = node_data.export.properties
                            match node_data.classname:
                                case 'MaterialExpressionFunctionInput':
                                    input_positions.append(node_data.node.location)
                                    node_tree.inputs.new(ue_to_bl_type.get(props.TryGetValue('InputType', 'FunctionInput_Vector3'), 'NodeSocketVector'), props.TryGetValue('InputName', "In"))
                                    node_tree.links.new(in_node.outputs[len(node_tree.inputs)-1], node_data.node.inputs[0])
                                case 'MaterialExpressionFunctionOutput':
                                    output_positions.append(node_data.node.location)
                                    node_tree.outputs.new('NodeSocketVector', props.TryGetValue('OutputName', "Result"))
                                    node_tree.links.new(node_data.node.outputs[0], out_node.inputs[len(node_tree.outputs)-1])
                    
                    in_pos = Vector((0,0))
                    for pos in input_positions: in_pos += pos
                    in_node.location = in_pos / len(input_positions) + Vector((-300,50))

                    out_pos = Vector((0,0))
                    for pos in output_positions: out_pos += pos
                    out_node.location = out_pos / len(output_positions) + Vector((200,50))

                    for name in nodes_data:
                        LinkSockets(node_tree, nodes_data, nodes_data[name]) # TODO: this iterates nodes without links!
    
    if log: print(f"Imported {mat.name}: {(time.time() - t0) * 1000:.2f}ms")
    return (out, graph_data)
def TryGetUMaterialImport(mat_imp:Import, mesh=None):
    mat = bpy.data.materials.get(mat_imp.object_name)
    if not mat:
        umat_path = mat_imp.asset.ToProjectPath(mat_imp.import_ref.object_name)
        try: mat, graph_data = ImportNodeGraph(umat_path, mat_imp.asset.uproject, mesh=mesh)
        except Exception as e:
            print(f"Failed to Import {mat_imp.object_name}: {e}")
            pass
    return mat

def menu_import_umat(self, context): self.layout.operator(ImportUMat.bl_idname, text="UE Material (.uasset)")
class ImportUMat(bpy.types.Operator, ImportHelper):
    """Import Unreal Engine Material File"""
    bl_idname    = "import.umat"
    bl_label     = "Import"
    filename_ext = ".uasset"
    filter_glob: StringProperty(default="*.uasset", options={'HIDDEN'}, maxlen=255)
    files:       CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN','SKIP_SAVE'})
    directory:   StringProperty(options={'HIDDEN'})

    def execute(self, context):
        for file in self.files:
            if file.name != "": ImportNodeGraph(self.directory + file.name)
        return {'FINISHED'}

reg_classes = ( ImportUMat, )

def register():
    register_helper.RegisterClasses(reg_classes)
    register_helper.RegisterDrawFnc(bpy.types.TOPBAR_MT_file_import, ImportUMat, menu_import_umat)
def unregister():
    register_helper.TryUnregisterClasses(reg_classes)
    register_helper.UnregisterDrawFnc(bpy.types.TOPBAR_MT_file_import, ImportUMat, menu_import_umat)

if __name__ != "umat":
    importlib.reload(uasset)
    unregister()
    register()

    for mat in bpy.data.materials: bpy.data.materials.remove(mat)
    for group in bpy.data.node_groups: bpy.data.node_groups.remove(group)

    #filepath = r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Materials\M_Base_Trim.uasset"
    #filepath = r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Materials\MI_Trim_A_Red2.uasset"
    #filepath = r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\NewMaterial.uasset"
    #filepath = r"F:\Projects\Unreal Projects\Assets\Content\Test1434.uasset"
    #filepath = r"C:\Program Files\Epic Games\UE_4.27\Engine\Content\EngineMaterials\DefaultMaterial.uasset"
    filepath = r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\StarterBundle\ModularScifiProps\Materials\MI_Laptop_Mail.uasset"
    ImportNodeGraph(filepath)
    print("Done")