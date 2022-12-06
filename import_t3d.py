import bpy, re, os, glob, time, pathlib
from mathutils import *

filename = "M_Base_Trim.T3D"
#filename = "MI_Trim_A_Red2.T3D"
export_dir = "F:\Art\Assets"
filename = bpy.path.abspath("//" + filename)
export_dir = os.path.normpath(export_dir)


t3d_block = re.compile(r"( *)Begin\s+(\w+)\s+(?:Class=(.+?)\s+)?Name=\"(.+?)\"(.*?)\r?\n\1End\s+\2", re.DOTALL | re.IGNORECASE)
block_parameters = re.compile(r"(\w+(?:\(\d+\))?)\s*=\s*(.+?)\r?\n", re.MULTILINE)
inline_parameter = re.compile(r"([\w\d]+)=([^,\r\n]+)")
parse_rgba = re.compile(r"\s*\(\s*R\s*=\s*(.+?)\s*,\s*G\s*=\s*(.+?)\s*,\s*B\s*=\s*(.+?)\s*,\s*A\s*=\s*(.+?)\s*\)", re.DOTALL | re.IGNORECASE)
parse_socket_expression = re.compile(r"(.+?)'\"(?:(.+?):)?(.+?)\"'", re.S)

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
    def __init__(self, classname, node=None, params=None, link_indirect=None):
        self.classname = classname
        self.node = node
        self.params = params
        self.link_indirect = link_indirect
class GraphData():
    def __init__(self):
        self.nodes_data = {}
        self.node_guids = {}


default_mapping = UE2BlenderNodeMapping('ShaderNodeMath', label="UNKNOWN", color=Color((1,0,0)))
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
material_classes = { 'Material', 'MaterialInstanceConstant' }
param_x = 'MaterialExpressionEditorX'
param_y = 'MaterialExpressionEditorY'
#safety_override = False

def SetupNode(node_tree, name, mapping, node_data):
    node = node_tree.nodes.new(mapping.bl_idname)
    node.name = name
    node.hide = mapping.hide
    if mapping.subtype:
        if mapping.bl_idname == 'ShaderNodeGroup': node.node_tree = bpy.data.node_groups[mapping.subtype]
        else: node.operation = mapping.subtype
    if mapping.label: node.label = mapping.label
    node.use_custom_color = mapping.color != None
    if mapping.color: node.color = mapping.color

    if mapping.bl_idname == 'ShaderNodeTexImage':
        rgba = node_tree.nodes.new('ShaderNodeGroup')
        rgba.node_tree = bpy.data.node_groups['RGBA']
        rgba.hide = True
        node_tree.links.new(node.outputs['Color'], rgba.inputs['RGB'])
        node_tree.links.new(node.outputs['Alpha'], rgba.inputs['A'])
        node_data.link_indirect = rgba.outputs
    return node
def ParseParams(text, regex=block_parameters): return { m.group(1): m.group(2) for m in regex.finditer(text) }
def GetBasepath(expression_text):
    m = parse_socket_expression.match(expression_text)
    #type = m.group(1)
    return os.path.join(export_dir, os.path.normpath(m.group(3).lstrip('/').split('.')[0]))
def TryGetFilepath(base_path):
    potential_paths = glob.glob(base_path + ".*")
    return potential_paths[0] if len(potential_paths) > 0 else None
def SetPos(node, param_x, param_y, params):
    if param_x in params and param_y in params: node.location = (int(params[param_x]), -int(params[param_y]))
def LinkSocket(mat, nodes_data, node, paramName, expression_text, socket_mapping):
    socket_params = ParseParams(expression_text.strip("()"), inline_parameter)
    #print(socket_params)

    key = 'Expression' if 'Expression' in socket_params else 'Input' # TODO: more robust

    m = parse_socket_expression.match(socket_params[key])
    if m:
        link_node_type = m.group(1)
        link_mat = m.group(2)
        link_node_name = m.group(3)
        if not link_mat or link_mat == mat.name:
            if link_node_name in nodes_data:
                #print(link_node_name + "->" + node.name)
                link_node_data = nodes_data[link_node_name]
                link_node = link_node_data.node
                src_socket = None
                dst_socket = None
                src_index = 0

                if 'OutputIndex' in socket_params: src_index = int(socket_params['OutputIndex'])

                if link_node_data.link_indirect: outputs = link_node_data.link_indirect
                else: outputs = link_node.outputs
                src_socket = outputs[src_index]

                if paramName in socket_mapping: 
                    dst_index = socket_mapping[paramName]
                    if link_node_type == 'MaterialExpressionAppendVector' and node.bl_idname == 'ShaderNodeCombineXYZ':
                        raise Exception("Unreal's append is annoying")
                        # TODO: move to LinkSockets and handle all Append sockets at once
                        dst_index = 2
                        sep = mat.node_tree.nodes.new('ShaderNodeSeparateXYZ')
                        sep.location = link_node.location + Vector((100,0))
                        mat.node_tree.links.new(link_node.outputs[0], sep.inputs[0])
                        mat.node_tree.links.new(sep.outputs[0], node.inputs[0])
                        mat.node_tree.links.new(sep.outputs[1], node.inputs[1])
                        mat.node_tree.links.new(sep.outputs[2], node.inputs[2])
                    
                    dst_socket = node.inputs[dst_index]
                else: print(f"UNKNOWN PARAM: {node.name}.{paramName}")

                if src_socket and dst_socket: mat.node_tree.links.new(src_socket, dst_socket)
                else: print(f"FAILED LINK: {node.name}.{paramName}")
            else: print(f"MISSING NODE: {str(link_node_name)}")
        else: print(f"UNKNOWN MAT: {str(link_mat)}")
    else: print(f"FAILED LINK, PARSE FAIL: {expression_text}")
def LinkSockets(mat, nodes_data, node_data):
    if node_data.classname in UE2BlenderNode_dict:
        mapping = UE2BlenderNode_dict[node_data.classname]
        if mapping.inputs:
            for ue_socket_name in mapping.inputs:
                if ue_socket_name in node_data.params:
                    try:
                        LinkSocket(mat, nodes_data, node_data.node, ue_socket_name, node_data.params[ue_socket_name], mapping.inputs)
                    except Exception as e:
                        print(f"LINK EXCEPTION: {node_data.node.name}.{ue_socket_name}")
                        print(e)
                        pass
def ImportT3D(filename, mat=None):
    graph_data = None
    t0 = time.time()
    print(f"Import \"{filename}\"")
    t3d_text = pathlib.Path(filename).read_text()

    header = t3d_block.match(t3d_text)
    if header:
        type = header.group(2)
        object_classname = header.group(3).split('.')[-1]

        if type == 'Object' and object_classname in material_classes:
            mat_name = header.group(4)
            object_body = header.group(5)

            print(f"post-body-parse {(time.time() - t0)*1000:.2f}ms")

            if mat_name in bpy.data.materials: bpy.data.materials.remove(bpy.data.materials[mat_name])
            if not mat:
                mat = bpy.data.materials.new(mat_name)
                mat.use_nodes = True
            node_tree = mat.node_tree

            graph_data = GraphData()
            nodes_data = graph_data.nodes_data

            for m_object in t3d_block.finditer(object_body):
                #type = m_object.group(2)
                classname = m_object.group(3)
                name = m_object.group(4)

                if classname:
                    classname = classname.split('.')[-1]
                    nodes_data[name] = node_data = NodeData(classname)
                    if classname in class_blacklist: continue

                    isnt_fnc = classname != 'MaterialExpressionMaterialFunctionCall'
                    
                    if classname in UE2BlenderNode_dict: mapping = UE2BlenderNode_dict[classname]
                    elif isnt_fnc:
                        print(f"UNKNOWN CLASS: {classname}")
                        mapping = default_mapping
                    
                    if isnt_fnc: node_data.node = SetupNode(node_tree, name, mapping, node_data) # TODO: always defer creation?
                else:
                    if name in nodes_data:# TODO: redundant, always true?
                        node_data = nodes_data[name]
                        classname = node_data.classname

                        if classname in class_blacklist: continue

                        body = m_object.group(5)
                        node_data.params = params = ParseParams(body)
                        #print(params)

                        if classname == 'MaterialExpressionMaterialFunctionCall':
                            node_data.classname = classname = params['MaterialFunction'].split('.')[-1].strip('\"\'')
                            node_data.node = node = SetupNode(node_tree, name, UE2BlenderNode_dict[classname], node_data)
                        else: node = node_data.node
                        
                        SetPos(node, param_x, param_y, params)
                        if 'SizeX' in params and 'SizeY' in params:
                            node.width = int(params['SizeX'])
                            node.height = int(params['SizeY'])
                        if 'Text' in params: node.label = params['Text'].strip('\"')
                        elif 'ParameterName' in params: node.label = params['ParameterName'].strip('\"')
                        if 'DefaultValue' in params: # TODO: move to mapping class?
                            valueStr = params['DefaultValue']
                            match classname:
                                case 'MaterialExpressionScalarParameter':
                                    node.outputs[0].default_value = float(valueStr)
                                case 'MaterialExpressionVectorParameter':
                                    m = parse_rgba.match(valueStr)
                                    node.inputs['RGB'].default_value = (float(m.group(1)), float(m.group(2)), float(m.group(3)), 1)
                                    node.inputs['A'].default_value = float(m.group(4))
                                case 'MaterialExpressionStaticSwitchParameter':
                                    node.inputs['Fac'].default_value = 1 if valueStr == "True" else 0
                        if 'CoordinateIndex' in params:
                            obj = bpy.context.object # TODO: less fragile?
                            node.uv_map = obj.data.uv_layers.keys()[int(params['CoordinateIndex'])]
                        if 'Texture' in params:
                            base_path = GetBasepath(params['Texture'])
                            texture_path = TryGetFilepath(base_path)
                            if texture_path:
                                print(texture_path)
                                node.image = bpy.data.images.load(texture_path)
                            else: print(f"Missing Texture \"{base_path}\"")
                        if 'ExpressionGUID' in params: graph_data.node_guids[params['ExpressionGUID']] = node_data

                        if node_data.link_indirect: node_data.link_indirect.data.location = node.location + Vector((100,30))
                    else: print("NODE NOT FOUND: " + name)
            
            print(f"t1 {(time.time() - t0)*1000:.2f}ms")

            match object_classname:
                case 'Material':
                    t0_link = time.time()
                    for name in nodes_data: LinkSockets(mat, nodes_data, nodes_data[name])
                    print(f"links {(time.time() - t0_link)*1000:.2f}ms")

                    mat_remaining_text = object_body[m_object.end(0):]
                    node = node_tree.nodes['Principled BSDF']
                    node_data = NodeData(object_classname, node, ParseParams(mat_remaining_text))
                    SetPos(node, 'EditorX', 'EditorY', node_data.params)
                    node_tree.nodes['Material Output'].location = node.location + Vector((300,0))
                    LinkSockets(mat, nodes_data, node_data)
                    # TODO: store output node in nodes_data?
                case 'MaterialInstanceConstant':
                    print("Material Instance")
                    mat_remaining_text = object_body[m_object.end(0):]
                    params = ParseParams(mat_remaining_text)
                    #print(params)
                    
                    base_path = GetBasepath(params['Parent'])
                    mat_path = TryGetFilepath(base_path)
                    if mat_path:
                        graph_data = ImportT3D(mat_path, mat)
                        raise Exception("Need to get returned cached data?")
                    else: print(f"Missing Material \"{base_path}\"")

                    for key in params:
                        spl = key.split('(')
                        if len(spl) > 1:
                            socket_params = ParseParams(params[key].strip("()"), inline_parameter)
                            if 'ParameterValue' in socket_params: 
                                value_text = socket_params['ParameterValue']
                                guid = socket_params['ExpressionGUID']
                                match spl[0]: # TODO: method parse param to node value? - ehh, classnames are different
                                    case 'ScalarParameterValues':
                                        print(key)
                                        value = float(value_text)
                                    case 'VectorParameterValues':
                                        print(key)
                                    case 'TextureParameterValues':
                                        print(key)
                                        base_path = GetBasepath(value_text)
                                        texture_path = TryGetFilepath(base_path)
                                        if texture_path:
                                            print(texture_path)
                                            raise Exception("TODO: get node")
                                            node.image = bpy.data.images.load(texture_path)
                                        else: print(f"Missing Texture \"{base_path}\"")

    print(f"Imported {mat_name}: {(time.time() - t0) * 1000:.2f}ms")
    return graph_data

ImportT3D(filename)