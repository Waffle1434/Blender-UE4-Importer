import bpy, re, os, glob
from mathutils import Vector

print("start")

filename = "M_Base_Trim.T3D"
export_dir = "F:\Art\Assets"
filename = bpy.path.abspath("//" + filename)
export_dir = os.path.normpath(export_dir)

t3d_block = re.compile(r"( *)Begin\s+(\w+)\s+(?:Class=(.+?)\s+)?Name=\"(.+?)\"(.*?)\r?\n\1End\s+\2", re.DOTALL | re.IGNORECASE)
block_parameters = re.compile(r"(\w+(?:\(\d+\))?)\s*=\s*(.+?)\r?\n", re.MULTILINE)
inline_parameter = re.compile(r"([\w\d]+)=([^,\r\n]+)")
parse_rgba = re.compile(r"\s*\(\s*R\s*=\s*(.+?)\s*,\s*G\s*=\s*(.+?)\s*,\s*B\s*=\s*(.+?)\s*,\s*A\s*=\s*(.+?)\s*\)", re.DOTALL | re.IGNORECASE)
parse_socket_expression = re.compile(r"(.+?)'\"(?:(.+?):)?(.+?)\"'", re.S)

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
    'Material' : UE2BlenderNodeMapping('ShaderNodeBsdfPrincipled', hide=False, inputs={'BaseColor':'Base Color','Metallic':'Metallic','Specular':'Specular','Roughness':'Roughness','Normal':'Normal'}),
    'MaterialExpressionAdd' : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='ADD', inputs={'A':0,'B':1}),
    'MaterialExpressionMultiply' : UE2BlenderNodeMapping('ShaderNodeVectorMath', subtype='MULTIPLY', inputs={'A':0,'B':1}),
    'MaterialExpressionScalarParameter' : UE2BlenderNodeMapping('ShaderNodeValue', hide=False),
    'MaterialExpressionVectorParameter' : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='RGBA', hide=False, outputs={'RGB':0,'R':1,'G':2,'B':3,'A':4}),
    'MaterialExpressionStaticSwitchParameter' : UE2BlenderNodeMapping('ShaderNodeMixRGB', hide=False, inputs={'A':1,'B':2}),
    'MaterialExpressionAppendVector' : UE2BlenderNodeMapping('ShaderNodeCombineXYZ', label="Append", inputs={'A':0,'B':1}),
    'MaterialExpressionLinearInterpolate' : UE2BlenderNodeMapping('ShaderNodeMixRGB', label="Lerp", inputs={'A':1,'B':2,'Alpha':0}),
    'MaterialExpressionClamp' : UE2BlenderNodeMapping('ShaderNodeClamp', inputs={'Input':0,'Min':1,'Max':2}),
    'MaterialExpressionTextureSampleParameter2D' : UE2BlenderNodeMapping('ShaderNodeTexImage', hide=False, inputs={'Coordinates':0}),
    'MaterialExpressionTextureCoordinate' : UE2BlenderNodeMapping('ShaderNodeUVMap', hide=False),
    'MaterialExpressionDesaturation' : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='Desaturation', inputs={'Input':0,'Fraction':1}),
    'MaterialExpressionComment' : UE2BlenderNodeMapping('NodeFrame'),
    'CheapContrast_RGB' : UE2BlenderNodeMapping('ShaderNodeBrightContrast', hide=False, inputs={'FunctionInputs(0)':'Color','FunctionInputs(1)':'Contrast'}),
    'BlendAngleCorrectedNormals' : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='BlendAngleCorrectedNormals', hide=False, inputs={'FunctionInputs(0)':0,'FunctionInputs(1)':1}),
}
class_blacklist = { 'SceneThumbnailInfoWithPrimitive' }
param_x = 'MaterialExpressionEditorX'
param_y = 'MaterialExpressionEditorY'

def SetupNode(name, mapping):
    node = mat.node_tree.nodes.new(mapping.bl_idname)
    node.name = name
    node.hide = mapping.hide
    if mapping.subtype:
        if mapping.bl_idname == 'ShaderNodeGroup': node.node_tree = bpy.data.node_groups[mapping.subtype]
        else: node.operation = mapping.subtype
    if mapping.label: node.label = mapping.label

    if mapping.bl_idname == 'ShaderNodeTexImage':
        rgba = mat.node_tree.nodes.new('ShaderNodeGroup')
        rgba.node_tree = bpy.data.node_groups['RGBA']
        rgba.hide = True
        mat.node_tree.links.new(node.outputs['Color'], rgba.inputs['RGB'])
        mat.node_tree.links.new(node.outputs['Alpha'], rgba.inputs['A'])
        link_indirection[name] = rgba.outputs
    return node
def ParseParams(text, regex=block_parameters): return { m.group(1): m.group(2) for m in regex.finditer(text) }
def SetPos(node, param_x, param_y, params):
    if param_x in params and param_y in params: node.location = (int(params[param_x]), -int(params[param_y]))
def LinkSocket(mat, nodes, node, paramName, expression_text, socket_mapping):
    socket_params = ParseParams(expression_text.strip("()"), inline_parameter)
    #print(socket_params)

    key = 'Expression' if 'Expression' in socket_params else 'Input' # TODO: more robust

    m = parse_socket_expression.match(socket_params[key])
    if m:
        #link_node_type = m.group(1)
        link_mat = m.group(2)
        link_node_name = m.group(3)
        if not link_mat or link_mat == mat.name:
            if link_node_name in nodes:
                #print(link_node_name + "->" + node.name)
                link_node = nodes[link_node_name]
                src_socket = None
                dst_socket = None
                src_index = 0
                #if link_node_name == 'MaterialExpressionVectorParameter_2': print(socket_params)

                if 'OutputIndex' in socket_params: src_index = int(socket_params['OutputIndex'])

                if link_node.name in link_indirection: outputs = link_indirection[link_node.name]
                else: outputs = link_node.outputs
                src_socket = outputs[src_index]

                if paramName in socket_mapping: dst_socket = node.inputs[socket_mapping[paramName]]
                else: print(f"UNKNOWN PARAM: {node.name}.{paramName}")

                if src_socket and dst_socket: mat.node_tree.links.new(src_socket, dst_socket)
                else: print(f"FAILED LINK: {node.name}.{paramName}")
            else: print(f"MISSING NODE: {str(link_node_name)}")
        else: print(f"UNKNOWN MAT: {str(link_mat)}")
    else: print(f"FAILED LINK, PARSE FAIL: {expression_text}")
def LinkSockets(mat, nodes, node, classpath, params):
    if classpath in UE2BlenderNode_dict:
        mapping = UE2BlenderNode_dict[classpath]
        inputs = mapping.inputs
        if inputs:
            for ue_socket_name in inputs:
                if ue_socket_name in params:
                    try:
                        LinkSocket(mat, nodes, node, ue_socket_name, params[ue_socket_name], mapping.inputs)
                    except Exception as e:
                        print(f"LINK EXCEPTION: {node.name}.{ue_socket_name}")
                        print(e)
                        pass

with open(filename, 'r') as file: t3d_text = file.read()

header = t3d_block.match(t3d_text)
if header:
    type = header.group(2)
    classpath = header.group(3)

    if type == 'Object' and classpath == '/Script/Engine.Material':
        mat_name = header.group(4)
        object_body = header.group(5)

        if mat_name in bpy.data.materials: bpy.data.materials.remove(bpy.data.materials[mat_name])
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True

        nodes = {}
        node_classes = {}
        link_indirection = {}
        nodes_params = {}

        for m_object in t3d_block.finditer(object_body):
            #type = m_object.group(2)
            classpath = m_object.group(3)
            name = m_object.group(4)

            if classpath:
                classpath = classpath.split('.')[-1]
                node_classes[name] = classpath # TODO: move into some kind of class?
                if classpath in class_blacklist: continue

                isnt_fnc = classpath != 'MaterialExpressionMaterialFunctionCall'
                
                if classpath in UE2BlenderNode_dict: mapping = UE2BlenderNode_dict[classpath]
                elif isnt_fnc:
                    print(f"UNKNOWN CLASS: {classpath}")
                    mapping = default_mapping
                
                if isnt_fnc: nodes[name] = SetupNode(name, mapping)
                else: nodes[name] = None
            else:
                classpath = node_classes[name]
                if classpath in class_blacklist: continue

                if name in nodes:
                    body = m_object.group(5)
                    params = ParseParams(body)
                    #print(params)

                    if classpath == 'MaterialExpressionMaterialFunctionCall':
                        node_classes[name] = classpath = params['MaterialFunction'].split('.')[-1].strip('\"\'')
                        nodes[name] = node = SetupNode(name, UE2BlenderNode_dict[classpath])
                    else: node = nodes[name]
                    
                    SetPos(node, param_x, param_y, params)
                    if 'SizeX' in params and 'SizeY' in params:
                        node.width = int(params['SizeX'])
                        node.height = int(params['SizeY'])
                    if 'Text' in params: node.label = params['Text'].strip('\"')
                    elif 'ParameterName' in params: node.label = params['ParameterName'].strip('\"')
                    if 'DefaultValue' in params: # TODO: move to mapping class?
                        valueStr = params['DefaultValue']
                        match classpath:
                            case 'MaterialExpressionScalarParameter':
                                node.outputs[0].default_value = float(valueStr)
                            case 'MaterialExpressionVectorParameter':
                                m = parse_rgba.match(valueStr)
                                node.inputs['RGB'].default_value = (float(m.group(1)), float(m.group(2)), float(m.group(3)), 1)
                                node.inputs['A'].default_value = float(m.group(4))
                                #node.outputs[0].default_value = (float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)))
                            case 'MaterialExpressionStaticSwitchParameter':
                                node.inputs['Fac'].default_value = 1 if valueStr == "True" else 0
                    if 'CoordinateIndex' in params:
                        obj = bpy.context.object # TODO: less fragile?
                        node.uv_map = obj.data.uv_layers.keys()[int(params['CoordinateIndex'])]
                    if 'Texture' in params:
                        m = parse_socket_expression.match(params['Texture'])
                        #texture_type = m.group(1)
                        base_path = os.path.join(export_dir, os.path.normpath(m.group(3).lstrip('/').split('.')[0]))
                        potential_paths = glob.glob(base_path + ".*")
                        if len(potential_paths) > 0:
                            texture_path = potential_paths[0]
                            print(texture_path)
                            node.image = bpy.data.images.load(texture_path)
                        else: print(f"Missing Texture \"{base_path}\"")

                    if name in link_indirection: link_indirection[name].data.location = node.location + Vector((100,30))

                    #LinkSockets(mat, nodes, node, classpath, params)
                    nodes_params[name] = params
                else: print("NODE NOT FOUND: " + name)
        
        for name in nodes_params:
            node = nodes[name]
            classpath = node_classes[name]
            LinkSockets(mat, nodes, node, classpath, nodes_params[name])

        mat_remaining_text = object_body[m_object.end(0):]
        params = ParseParams(mat_remaining_text)
        node = mat.node_tree.nodes['Principled BSDF']
        SetPos(node, 'EditorX', 'EditorY', params)
        mat.node_tree.nodes['Material Output'].location = node.location + Vector((300,0))
        LinkSockets(mat, nodes, node, 'Material', params)
print("done")