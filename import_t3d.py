import bpy, re, os, glob, time, pathlib
from mathutils import *
from bpy_extras.io_utils import ImportHelper
from bpy.props import *
from bpy.types import Operator

#filename = "M_Base_Trim.T3D"
filename = "MI_Trim_A_Red2.T3D"
#base_dir = "F:\Art\Assets"
filename = bpy.path.abspath(f"//Samples//{filename}")
logging = False
mute_ior = True
mute_fresnel = True

t3d_block = re.compile(r"( *)Begin\s+(\w+)\s+(?:Class=(.+?)\s+)?Name=\"(.+?)\"(.*?)\r?\n\1End\s+\2", re.DOTALL | re.IGNORECASE)
block_parameters = re.compile(r"(\w+(?:\(\d+\))?)=(.+?)\r?\n", re.MULTILINE)
inline_parameter = re.compile(r"([\w\d]+)=((?:\(.+?\))|(?:[^,\n]+))")
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
    def __init__(self, classname, node=None, params=None, link_indirect=None, input_remap=None):
        self.classname = classname
        self.node = node
        self.params = params
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
    'CheapContrast_RGB' : UE2BlenderNodeMapping('ShaderNodeBrightContrast', hide=False, inputs={'FunctionInputs(0)':'Color','FunctionInputs(1)':'Contrast'}),
    'BlendAngleCorrectedNormals' : UE2BlenderNodeMapping('ShaderNodeGroup', subtype='BlendAngleCorrectedNormals', hide=False, inputs={'FunctionInputs(0)':0,'FunctionInputs(1)':1}),
}
class_blacklist = { 'SceneThumbnailInfoWithPrimitive', 'MaterialExpressionPanner' }
material_classes = { 'Material', 'MaterialInstanceConstant' }
node_whitelist = { 'ShaderNodeBsdfPrincipled', 'ShaderNodeOutputMaterial' }
param_x = 'MaterialExpressionEditorX'
param_y = 'MaterialExpressionEditorY'
#safety_override = False

def DeDuplicateName(name):
    i = name.rfind('.')
    return name[:i] if i >= 0 else name

def SetupNode(node_tree, name, mapping, node_data): # TODO: inline
    node = node_tree.nodes.new(mapping.bl_idname)
    node.name = name
    node.hide = mapping.hide
    if mapping.subtype:
        if mapping.bl_idname == 'ShaderNodeGroup': node.node_tree = bpy.data.node_groups[mapping.subtype]
        else: node.operation = mapping.subtype
    if mapping.label: node.label = mapping.label
    node.use_custom_color = mapping.color != None
    if mapping.color: node.color = mapping.color

    match mapping.bl_idname:
        case 'ShaderNodeTexImage':
            rgb_in = node.outputs['Color']
            if node_data.params.get('SamplerType') == 'SAMPLERTYPE_Normal':
                rgb2n = node_tree.nodes.new('ShaderNodeGroup')
                rgb2n.node_tree = bpy.data.node_groups['RGBtoNormal']
                rgb2n.hide = True
                SetPos(rgb2n, param_x, param_y, node_data.params)
                rgb2n.location += Vector((-50,30))
                node_tree.links.new(node.outputs['Color'], rgb2n.inputs['RGB'])
                rgb_in = rgb2n.outputs['Normal']

            rgba = node_tree.nodes.new('ShaderNodeGroup')
            rgba.node_tree = bpy.data.node_groups['RGBA']
            rgba.hide = True
            node_tree.links.new(rgb_in, rgba.inputs['RGB'])
            node_tree.links.new(node.outputs['Alpha'], rgba.inputs['A'])
            node_data.link_indirect = rgba.outputs
        case 'ShaderNodeMixRGB':
            node.inputs['Fac'].default_value = 0
    return node
def ParseParams(text, regex=block_parameters): return { m.group(1): m.group(2) for m in regex.finditer(text) }
def GuessBaseDir(filename): return filename[:filename.find("Game")] # Unreal defaults to starting path with "Game" on asset export
def GetFullPath(base_dir, expression_text):
    m = parse_socket_expression.match(expression_text)
    #type = m.group(1)
    return os.path.join(base_dir, os.path.normpath(m.group(3).lstrip('/').split('.')[0]))
def TryGetFilepath(extensionless_path):
    potential_paths = glob.glob(extensionless_path + ".*")
    return potential_paths[0] if len(potential_paths) > 0 else None
def SetPos(node, param_x, param_y, params): node.location = (int(params.get(param_x,"0")), -int(params.get(param_y,"0")))
def LinkSocket(mat, nodes_data, node_data, param_name, expression_text, socket_mapping):
    socket_params = ParseParams(expression_text.strip("()"), inline_parameter)
    #print(socket_params)

    key = 'Expression' if 'Expression' in socket_params else 'Input' # TODO: more robust

    m = parse_socket_expression.match(socket_params[key])
    if m:
        link_node_type = m.group(1)
        #link_mat = m.group(2)
        link_node_name = m.group(3)
        if link_node_name in nodes_data:
            link_node_data = nodes_data[link_node_name]
            if link_node_data.classname in class_blacklist: return
            
            node = node_data.node
            link_node = link_node_data.node
            src_socket = None
            dst_socket = None
            src_index = 0

            if 'OutputIndex' in socket_params: src_index = int(socket_params['OutputIndex'])

            if link_node_data.link_indirect: outputs = link_node_data.link_indirect
            else: outputs = link_node.outputs
            src_socket = outputs[src_index]

            if param_name in socket_mapping: 
                dst_index = socket_mapping[param_name]
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
            else: print(f"UNKNOWN PARAM: {node.name}.{param_name}")

            if node_data.input_remap and param_name in node_data.input_remap: dst_socket = node_data.input_remap[param_name]

            if src_socket and dst_socket:
                link = mat.node_tree.links.new(src_socket, dst_socket)
                if mute_fresnel and src_socket.node.bl_idname == 'ShaderNodeFresnel': link.is_muted = True
            else: print(f"FAILED LINK: {node.name}.{param_name}")
        else: print(f"MISSING NODE: {str(link_node_name)}")
    else: print(f"FAILED LINK, PARSE FAIL: {expression_text}")
def LinkSockets(mat, nodes_data, node_data):
    if node_data.classname in UE2BlenderNode_dict:
        mapping = UE2BlenderNode_dict[node_data.classname]
        if mapping.inputs:
            for ue_socket_name in mapping.inputs:
                if ue_socket_name in node_data.params:
                    try:
                        LinkSocket(mat, nodes_data, node_data, ue_socket_name, node_data.params[ue_socket_name], mapping.inputs)
                    except Exception as e:
                        print(f"LINK EXCEPTION: {node_data.node.name}.{ue_socket_name}")
                        print(e)
                        pass
def ImportT3D(filename, mat=None, mat_object=None, base_dir=""):
    t0 = time.time()
    graph_data = None
    if logging: print(f"Import \"{filename}\"")
    if base_dir != "": base_dir = os.path.normpath(base_dir)
    t3d_text = pathlib.Path(filename).read_text()

    header = t3d_block.match(t3d_text)
    if header:
        type = header.group(2)
        object_classname = header.group(3).split('.')[-1]

        if type == 'Object' and object_classname in material_classes:
            mat_name = header.group(4)
            object_body = header.group(5)

            if mat_name in bpy.data.materials:# TODO: redundant?
                mat = bpy.data.materials[mat_name]
                nodes = mat.node_tree.nodes
                for node in nodes:
                    if node.bl_idname not in node_whitelist: nodes.remove(node) 
            if not mat:
                mat = bpy.data.materials.new(mat_name)
                mat.use_nodes = True
            #mat.unreal = True
            node_tree = mat.node_tree

            graph_data = GraphData()
            nodes_data = graph_data.nodes_data

            for m_object in t3d_block.finditer(object_body):
                #type = m_object.group(2)
                classname = m_object.group(3)
                name = m_object.group(4)

                if classname:
                    nodes_data[name] = node_data = NodeData(classname.split('.')[-1])
                else:
                    if name in nodes_data:# TODO: redundant, always true?
                        node_data = nodes_data[name]
                        classname = node_data.classname

                        if classname in class_blacklist: continue

                        body = m_object.group(5)
                        node_data.params = params = ParseParams(body)
                        #print(params)

                        if classname == 'MaterialExpressionMaterialFunctionCall': node_data.classname = classname = params['MaterialFunction'].split('.')[-1].strip('\"\'')

                        if classname in UE2BlenderNode_dict: mapping = UE2BlenderNode_dict[classname]
                        else:
                            print(f"UNKNOWN CLASS: {classname}")
                            mapping = default_mapping
                        
                        node_data.node = node = SetupNode(node_tree, name, mapping, node_data)

                        SetPos(node, param_x, param_y, params)
                        if 'SizeX' in params and 'SizeY' in params:
                            node.width = int(params['SizeX'])
                            node.height = int(params['SizeY'])
                        if 'Text' in params: node.label = params['Text'].strip('\"')
                        elif 'ParameterName' in params: node.label = params['ParameterName'].strip('\"')
                        if 'DefaultValue' in params: # TODO: move to mapping class?
                            value_text = params['DefaultValue']
                            match classname:
                                case 'MaterialExpressionScalarParameter':
                                    node.outputs[0].default_value = float(value_text)
                                case 'MaterialExpressionVectorParameter':
                                    m = parse_rgba.match(value_text)
                                    node.inputs['RGB'].default_value = (float(m.group(1)), float(m.group(2)), float(m.group(3)), 1)
                                    node.inputs['A'].default_value = float(m.group(4))
                                case 'MaterialExpressionStaticSwitchParameter':
                                    node.inputs['Fac'].default_value = 1 if value_text == "True" else 0
                        if classname == 'MaterialExpressionConstant3Vector':
                            if 'Constant' in params:
                                value_text = params['Constant']
                                # TODO: unify with MaterialExpressionVectorParameter
                                m = parse_rgba.match(value_text)
                                node.inputs['RGB'].default_value = (float(m.group(1)), float(m.group(2)), float(m.group(3)), 1)
                                node.inputs['A'].default_value = float(m.group(4))
                        if 'CoordinateIndex' in params:
                            if mat_object == None: mat_object = bpy.context.object # TODO: less fragile?
                            node.uv_map = mat_object.data.uv_layers.keys()[int(params['CoordinateIndex'])]
                        if 'Texture' in params:
                            base_path = GetFullPath(base_dir, params['Texture'])
                            tex_path = TryGetFilepath(base_path)
                            if tex_path:
                                #print(tex_path)
                                node.image = bpy.data.images.load(tex_path, check_existing=True)
                                if params.get('SamplerType') == 'SAMPLERTYPE_Normal':
                                    node.image.colorspace_settings.name = 'Non-Color'
                                    node.interpolation = 'Smart'
                            else: print(f"Missing Texture \"{tex_path}\"")
                        if 'ExpressionGUID' in params: graph_data.node_guids[params['ExpressionGUID']] = node_data

                        if node_data.link_indirect: node_data.link_indirect.data.location = node.location + Vector((100,30))
                    else: print("NODE NOT FOUND: " + name)
            
            #print(f"t1 {(time.time() - t0)*1000:.2f}ms")

            match object_classname:
                case 'Material':
                    t0_link = time.time()
                    for name in nodes_data: LinkSockets(mat, nodes_data, nodes_data[name])
                    #print(f"links {(time.time() - t0_link)*1000:.2f}ms")

                    mat_remaining_text = object_body[m_object.end(0):]
                    node = node_tree.nodes['Principled BSDF']
                    node_data = NodeData(object_classname, node, ParseParams(mat_remaining_text))
                    params = node_data.params
                    SetPos(node, 'EditorX', 'EditorY', params)
                    node_tree.nodes['Material Output'].location = node.location + Vector((300,0))
                    match params.get('BlendMode'):
                        case 'BLEND_Translucent':
                            mat.blend_method = 'BLEND'
                            mat.shadow_method = 'HASHED'
                            node.inputs['Transmission'].default_value = 1
                        case 'BLEND_Masked':
                            mat.blend_method = 'CLIP'
                            mat.shadow_method = 'CLIP'
                        case _:
                            mat.blend_method = 'OPAQUE'
                            mat.shadow_method = 'OPAQUE'
                    mat.use_backface_culling = not params.get('TwoSided',False)

                    if 'Normal' in params:
                        normal_map = node_tree.nodes.new('ShaderNodeNormalMap')
                        normal_map.location = node.location + Vector((-200, -570))
                        # TODO: set normal uv
                        node_tree.links.new(normal_map.outputs['Normal'], node.inputs['Normal'])

                        n2rgb = node_tree.nodes.new('ShaderNodeGroup')
                        n2rgb.node_tree = bpy.data.node_groups['NormalToRGB']
                        n2rgb.location = normal_map.location + Vector((-160, -130))
                        n2rgb.hide = True
                        node_tree.links.new(n2rgb.outputs['RGB'], normal_map.inputs['Color'])

                        node_data.input_remap = { 'Normal':n2rgb.inputs['Normal'] }

                    LinkSockets(mat, nodes_data, node_data)
                    
                    ior = node.inputs['IOR']
                    if ior.is_linked: ior.links[0].is_muted = mute_ior

                    # TODO: store output node in nodes_data?
                case 'MaterialInstanceConstant':
                    mat_remaining_text = object_body[m_object.end(0):]
                    params = ParseParams(mat_remaining_text)
                    #print(params)

                    parent_mat_name = params['Parent'].split('.')[-1].rstrip('\"\'')
                    if logging: print(f"{parent_mat_name} Instance")
                    
                    base_path = GetFullPath(base_dir, params['Parent'])
                    mat_path = TryGetFilepath(base_path)
                    if mat_path:
                        ret = ImportT3D(mat_path, mat, mat_object, base_dir=base_dir)
                        mat = ret[0]
                        graph_data = ret[1]
                        
                        for key in params:
                            spl = key.split('(')
                            if len(spl) > 1:
                                socket_params = ParseParams(params[key].strip("()"), inline_parameter)
                                if 'ParameterValue' in socket_params: 
                                    value_text = socket_params['ParameterValue']
                                    node_data = graph_data.node_guids[socket_params['ExpressionGUID']]
                                    node = node_data.node
                                    match spl[0]: # TODO: method parse param to node value? - ehh, classnames are different, otherwise same
                                        case 'ScalarParameterValues':
                                            node.outputs[0].default_value = float(value_text)
                                        case 'VectorParameterValues':
                                            m = parse_rgba.match(value_text)
                                            node.inputs['RGB'].default_value = (float(m.group(1)), float(m.group(2)), float(m.group(3)), 1)
                                            node.inputs['A'].default_value = float(m.group(4))
                                        case 'TextureParameterValues':
                                            base_path = GetFullPath(base_dir, value_text)
                                            tex_path = TryGetFilepath(base_path)
                                            if tex_path:
                                                colorspace = node.image.colorspace_settings.name if node.image else None
                                                #print(tex_path)
                                                node.image = bpy.data.images.load(tex_path, check_existing=True)
                                                if colorspace: node.image.colorspace_settings.name = colorspace
                                            else: print(f"Missing Texture \"{base_path}\"")
                    else: print(f"Couldn't Find Material \"{base_path}\"")

    if logging: print(f"Imported {mat_name}: {(time.time() - t0) * 1000:.2f}ms")
    return (mat, graph_data)
def ImportObjectMaterials(object, base_dir="", force=False):
    mesh = object.data
    for i, mat in enumerate(mesh.materials):
        if not mat: continue
        spl = mat.name.split('.')
        mat_name = spl[0]
        if len(spl) > 1 and mat_name in bpy.data.materials:
            #bpy.data.materials.remove(mat) # TODO: this breaks multi model FBX's, defer, FBX caller should clean
            mesh.materials[i] = mat = bpy.data.materials[mat_name]
            if not force:
                print(f"Found Existing Material: {mat_name}")
                continue
        mat_files = glob.glob(f"{base_dir}\\**\\{mat_name}.T3D", recursive=True)
        if len(mat_files) > 0: mesh.materials[i] = ImportT3D(mat_files[0], mat, object, base_dir=base_dir)[0]
        else: print(f"Failed to find {mat_name}!")
def ImportObjectsMaterials(objects, base_dir="", force=False):
    if logging: print(f"Import Materials of {len(objects)} Objects")
    t0_objects = time.time()
    mat_dict = {} # TODO: use dictionary to prevent duplicates
    for object in objects:
        mesh = object.data
        for i, mat in enumerate(mesh.materials):
            if not mat: continue
            spl = mat.name.split('.')
            mat_name = spl[0]
            if len(spl) > 1 and mat_name in bpy.data.materials:
                mesh.materials[i] = mat = bpy.data.materials[mat_name] # TODO: should materials[i] assignment be here?
                if not force: print(f"Found Existing Material: {mat_name}")
            mat_dict[mat] = (mat_name, object)
    for mat in mat_dict:
        tup = mat_dict[mat]
        mat_name = tup[0]
        object = tup[1]
        mat_files = glob.glob(f"{base_dir}\\**\\{mat_name}.T3D", recursive=True)
        if len(mat_files) > 0: ImportT3D(mat_files[0], mat, object, base_dir=base_dir)[0]
        else: print(f"Failed to find {mat_name}!")
    if logging: print(f"Import: {(time.time() - t0_objects)*1000:.2f}ms\n")
def GetMeshObjects(objects): return filter(lambda o: o.type == 'MESH', objects)
def ImportSelectedObjectMaterials(base_dir="", force=True): ImportObjectsMaterials(GetMeshObjects(bpy.context.selected_objects), base_dir, force)
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
def ImportUnrealFbxAndMaterials(filepath, base_dir, collider_mode='NONE'):
        ImportUnrealFbx(filepath, collider_mode)
        mesh_objects = list(GetMeshObjects(bpy.context.selected_objects))
        ImportObjectsMaterials(mesh_objects, base_dir, True)
        return (mesh_objects)
def ReimportModels(objects, base_dir, collider_mode='NONE'):
    mesh_set = set()
    for object in objects: mesh_set.add(object.data)
    for mesh in mesh_set:
        mesh_name = DeDuplicateName(mesh.name)
        mesh_files = glob.glob(f"{base_dir}\\**\\*{mesh_name}.FBX", recursive=True)
        if len(mesh_files) > 0:
            mesh_objects = ImportUnrealFbxAndMaterials(mesh_files[0], base_dir, collider_mode)
            object = mesh_objects[0]
            mesh.user_remap(object.data)
            for object in mesh_objects: bpy.data.objects.remove(object)
            # TODO: delete old data?
        else: print(f"Failed to Find Mesh \"{mesh_name}\"")
def ImportFbxAndReimport(filepath, base_dir="", collider_mode='NONE'):
    bpy.ops.import_scene.fbx(filepath=filepath)
    if base_dir == "": base_dir = GuessBaseDir(filepath)
    ReimportModels(GetMeshObjects(bpy.context.selected_objects), base_dir, collider_mode)


#ImportT3D(filename, base_dir=base_dir)
#ImportSelectedObjectMaterials(base_dir=base_dir)
fbx_path = r"F:\Art\Assets\Game\ModSci_Engineer\Maps\Example_Stationary.FBX"
#ImportFbxAndReimport(fbx_path)


def EvalBaseDir(self): return GuessBaseDir(self.directory) if self.base_directory == "" else self.base_directory
class ImportT3D_Operator(Operator, ImportHelper):
    """Import Unreal Engine .T3D Material File"""
    bl_idname = "unreal_import.t3d"
    bl_label = "Import"
    filename_ext = ".T3D"
    filter_glob: StringProperty(default="*.T3D", options={'HIDDEN'}, maxlen=255)

    base_directory: StringProperty(name="Base Directory", description="Leave blank for auto detect. Directory which is the root of all the exported files. T3D files will refer to \"Texture=\" starting at this path.")

    def execute(self, context): 
        ImportT3D(self.filepath, base_dir=EvalBaseDir(self))
        return {'FINISHED'}
class ImportT3D_Materials(Operator):
    """Import Unreal Engine .T3D Materials"""
    bl_idname = "unreal_import.materials"
    bl_label = "Import Unreal Engine Materials"

    def execute(self, context): 
        ImportSelectedObjectMaterials() # TODO: get base path from model filepath
        return {'FINISHED'}
class ImportFBX_T3D_Operator(Operator, ImportHelper):
    """Import Unreal Engine .FBX & .T3D Materials"""
    bl_idname = "unreal_import.fbx_t3d"
    bl_label = "Import"
    filename_ext = ".FBX"
    filter_glob: StringProperty(default="*.FBX", options={'HIDDEN'}, maxlen=255)
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN','SKIP_SAVE'})
    directory: StringProperty(options={'HIDDEN'})

    collider_mode: EnumProperty(
        name="Colliders", default='NONE',
        items=(
            ('NONE', "None", "Exclude Colliders"),
            ('HIDE', "Hide", "Hide Colliders"),
            ('SHOW', "Show", "Show Colliders")
        )
    )
    base_directory: StringProperty(name="Base Directory", description="Leave blank for auto detect. Directory which is the root of all the exported files. T3D files will refer to \"Texture=\" starting at this path.")
    reimport_models: BoolProperty(name="Reimport Models", description="Fix FBX material errors by re-importing each mesh individually", default=True)

    def execute(self, context):
        base_dir = EvalBaseDir(self)
        for file in self.files:
            ImportUnrealFbxAndMaterials(self.directory + file.name, base_dir, self.collider_mode)
            if self.reimport_models and 'Fbx Default Material' in bpy.data.materials: ReimportModels(GetMeshObjects(bpy.context.selected_objects), base_dir, self.collider_mode)
        return {'FINISHED'}

def menu_import_t3d(self, context): self.layout.operator(ImportT3D_Operator.bl_idname, text="Unreal Engine Material (.T3D)")
def menu_import_fbx_t3d(self, context): self.layout.operator(ImportFBX_T3D_Operator.bl_idname, text="Unreal Engine FBX & Materials (.fbx)")

register_classes = ( ImportT3D_Operator, ImportT3D_Materials, ImportFBX_T3D_Operator )

persist_vars = bpy.app.driver_namespace
def registerDrawEvent(event, item):
    id = event.bl_rna.name
    handles = persist_vars.get(id, [])
    event.append(item)
    handles.append(item)
    persist_vars[id] = handles
def removeDrawEvents(event):
    for item in persist_vars.get(event.bl_rna.name,[]):
        try: event.remove(item)
        except: pass

def register():
    #bpy.types.Material.unreal = bpy.props.BoolProperty(name="Unreal Engine Material", description="Was this material imported from a .T3D file?", default=False)
    for cls in register_classes: bpy.utils.register_class(cls)
    registerDrawEvent(bpy.types.TOPBAR_MT_file_import, menu_import_t3d)
    registerDrawEvent(bpy.types.TOPBAR_MT_file_import, menu_import_fbx_t3d)
def unregister():
    #try: del bpy.types.Material.unreal
    #except: pass
    removeDrawEvents(bpy.types.TOPBAR_MT_file_import)
    for cls in register_classes:
        try: bpy.utils.unregister_class(cls)
        except: pass

if __name__ == "__main__":
    try: unregister()
    except: pass
    register()
