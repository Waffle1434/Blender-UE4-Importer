import bpy, re
from mathutils import Vector

print("start")

filename = "M_Base_Trim.T3D"
filename = bpy.path.abspath("//" + filename)

t3d_block = re.compile(r"( *)Begin\s+(\w+)\s+(?:Class=(.+?)\s+)?Name=\"(.+?)\"(.*?)\r?\n\1End\s+\2", re.DOTALL | re.IGNORECASE)
block_parameters = re.compile(r"(\w+)\s*=\s*(.+?)\r?\n", re.MULTILINE)
inline_parameter = re.compile(r"([\w\d]+)=([^,\r\n]+)")
parse_rgba = re.compile(r"\s*\(\s*R\s*=\s*(.+?)\s*,\s*G\s*=\s*(.+?)\s*,\s*B\s*=\s*(.+?)\s*,\s*A\s*=\s*(.+?)\s*\)", re.DOTALL | re.IGNORECASE)
#parse_socket_expression = re.compile(r"\(\s*Expression\s*=(.+?)'\"(.+?):(.+?)\"'\s*,?([\w=\d,]+)?\s*\)", re.DOTALL | re.IGNORECASE)
parse_socket_expression = re.compile(r"(.+?)'\"(.+?):(.+?)\"',?([\w=\d,]+)?\)", re.S)

class UE2BlenderNodeMapping():
    def __init__(self, bl_idname, subtype=None, label=None, hide=True, inputs=None, outputs=None):
        self.bl_idname = bl_idname
        self.subtype = subtype
        self.label = label
        self.hide = hide
        self.inputs = inputs
        self.outputs = outputs

default_mapping = UE2BlenderNodeMapping('ShaderNodeMath', label="UNKNOWN")
UE2BlenderNode_dict = {
    'MaterialExpressionAdd' : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='ADD', inputs={'A':0,'B':1}),
    'MaterialExpressionMultiply' : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='MULTIPLY', inputs={'A':0,'B':1}),
    'MaterialExpressionScalarParameter' : UE2BlenderNodeMapping('ShaderNodeValue', hide=False),
    'MaterialExpressionVectorParameter' : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='RGBA', hide=False, outputs={'RGB':0,'R':1,'G':2,'B':3,'A':4}),
    'MaterialExpressionStaticSwitchParameter' : UE2BlenderNodeMapping('ShaderNodeMixRGB', hide=False, inputs={'A':1,'B':2}),
    'MaterialExpressionAppendVector' : UE2BlenderNodeMapping('ShaderNodeCombineXYZ', label="Append", inputs={'A':0,'B':1}),
    'MaterialExpressionLinearInterpolate' : UE2BlenderNodeMapping('ShaderNodeMixRGB', label="Lerp", inputs={'A':1,'B':2,'Alpha':0}),
    'MaterialExpressionClamp' : UE2BlenderNodeMapping('ShaderNodeClamp', inputs={'Input':0,'Min':1,'Max':2}),
    'MaterialExpressionTextureSampleParameter2D' : UE2BlenderNodeMapping('ShaderNodeTexImage', hide=False),
    'MaterialExpressionTextureCoordinate' : UE2BlenderNodeMapping('ShaderNodeTexCoord', hide=False),
    'MaterialExpressionDesaturation' : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='Desaturation', inputs={'Input':0,'Fraction':1}),
    'MaterialExpressionComment' : UE2BlenderNodeMapping('NodeFrame'),
}
class_blacklist = { 'SceneThumbnailInfoWithPrimitive' }

param_x = "MaterialExpressionEditorX"
param_y = "MaterialExpressionEditorY"

def LinkSocket(mat, nodes, node, paramName, expressionText, socket_mapping):
    socket_params = {}
    for m in inline_parameter.finditer(expressionText.strip("()")): socket_params[m.group(1)] = m.group(2)
    #print(socket_params)

    m = parse_socket_expression.match(expressionText)
    if m:
        link_node_type = m.group(1)
        link_mat = m.group(2)
        link_node_name = m.group(3)
        if link_mat == mat.name:
            if link_node_name in nodes:
                link_node = nodes[link_node_name]
                src_socket = None
                dst_socket = None
                #if paramName == 'ALPHA': print("!" + node.name + "." + paramName)
                #if link_node_name == 'MaterialExpressionVectorParameter_2': print(socket_params)

                src_index = 0
                
                if 'OutputIndex' in socket_params: src_index = int(socket_params['OutputIndex'])
                
                match link_node_type:
                    case "MaterialExpressionTextureCoordinate": src_index = 'Generated'

                if link_node.name in link_indirection: outputs = link_indirection[link_node.name]
                else: outputs = link_node.outputs
                src_socket = outputs[src_index]

                if paramName in socket_mapping: dst_socket = node.inputs[socket_mapping[paramName]]
                else: print("UNKNOWN PARAM: " + node.name + "." + paramName)

                if src_socket and dst_socket: mat.node_tree.links.new(src_socket, dst_socket)
                else: print("FAILED LINK: " + node.name + "." + paramName)
            else: print("MISSING NODE: " + link_node_name)
        else: print("UNKNOWN MAT: " + link_mat)

with open(filename, 'r') as file:
    t3d_text = file.read()

#print(t3d_text)
header = t3d_block.match(t3d_text)
#print(header)
if header:
    type = header.group(2)
    classpath = header.group(3)

    if type == "Object" and classpath == "/Script/Engine.Material":
        # Load material
        mat_name = header.group(4)
        body = header.group(5)

        if mat_name in bpy.data.materials: bpy.data.materials.remove(bpy.data.materials[mat_name])
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True

        nodes = {}
        node_classes = {}
        link_indirection = {}

        for m in t3d_block.finditer(body):
            type = m.group(2)
            classpath = m.group(3)
            name = m.group(4)
            body = m.group(5)

            if classpath:
                classpath = classpath.split('.')[-1]
                node_classes[name] = classpath # TODO: move into some kind of class?

                if classpath in class_blacklist: continue
                
                if classpath in UE2BlenderNode_dict: mapping = UE2BlenderNode_dict[classpath]
                else:
                    print("UNKNOWN CLASS: " + classpath)
                    mapping = default_mapping
                
                nodes[name] = node = mat.node_tree.nodes.new(mapping.bl_idname)
                node.name = name
                node.hide = mapping.hide
                if mapping.subtype:
                    if mapping.bl_idname == 'ShaderNodeGroup': node.node_tree = bpy.data.node_groups[mapping.subtype]
                    else: node.operation = mapping.subtype
                if mapping.label: node.label = mapping.label

                if mapping.bl_idname == 'ShaderNodeTexImage':
                    rgba = mat.node_tree.nodes.new('ShaderNodeGroup')
                    rgba.node_tree = bpy.data.node_groups['RGBA']
                    mat.node_tree.links.new(node.outputs['Color'], rgba.inputs['RGB'])
                    mat.node_tree.links.new(node.outputs['Alpha'], rgba.inputs['A'])

                    link_indirection[name] = rgba.outputs
            else:
                classpath = node_classes[name]
                if classpath in class_blacklist: continue

                if name in nodes:
                    node = nodes[name]

                    params = {}
                    for m in block_parameters.finditer(body): params[m.group(1)] = m.group(2)
                    #print(params)
                    
                    if param_x in params and param_y in params: node.location = (int(params[param_x]), -int(params[param_y]))
                    if 'SizeX' in params and 'SizeY' in params:
                        node.width = int(params['SizeX'])
                        node.height = int(params['SizeY'])
                    if 'Text' in params: node.label = params['Text'].strip('\"')
                    elif 'ParameterName' in params: node.label = params['ParameterName'].strip('\"')

                    if 'DefaultValue' in params: # TODO: move to mapping class?
                        valueStr = params['DefaultValue']
                        match node.bl_idname:
                            case 'ShaderNodeValue':
                                node.outputs[0].default_value = float(valueStr)
                            case 'ShaderNodeRGB':
                                m = parse_rgba.match(valueStr)
                                node.outputs[0].default_value = (float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)))
                        match classpath:
                            case 'MaterialExpressionVectorParameter':
                                m = parse_rgba.match(valueStr)
                                node.inputs['RGB'].default_value = (float(m.group(1)), float(m.group(2)), float(m.group(3)), 1)
                                node.inputs['A'].default_value = float(m.group(4))
                            case 'MaterialExpressionStaticSwitchParameter':
                                node.inputs['Fac'].default_value = 1 if valueStr == "True" else 0
                    
                    if name in link_indirection:
                        link_indirection[name].data.location = node.location + Vector((200,0))

                    if classpath in UE2BlenderNode_dict:
                        mapping = UE2BlenderNode_dict[classpath]
                        inputs = mapping.inputs
                        if inputs:
                            for ue_socket_name in inputs:
                                if ue_socket_name in params:
                                    LinkSocket(mat, nodes, node, ue_socket_name, params[ue_socket_name], mapping.inputs)
                else:
                    print("NODE NOT FOUND: " + name)
                #elif len(body) > 0:
                    #print(">" + body + "<")
                    #print("no match")

print("done")