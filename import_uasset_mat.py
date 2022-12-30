from __future__ import annotations
import bpy, io, uuid, time, os, pathlib
from struct import *
from mathutils import *

#filepath = r"F:\Art\Assets\Game\Blender UE4 Importer\Samples\M_Base_Trim.uasset"
filepath = r"C:\Users\jdeacutis\Desktop\fSpy\New folder\Blender-UE4-Importer\Samples\M_Base_Trim.uasset"
exported_base_dir = r"F:\Art\Assets"
project_dir = r"F:\Projects\Unreal Projects\Assets"

logging = True

exported_base_dir = os.path.normpath(exported_base_dir)
project_dir = os.path.normpath(project_dir)

class ByteStream:
    def __init__(self, byte_stream:io.BufferedReader): self.byte_stream = byte_stream
    def __repr__(self) -> str: return f"\"{self.byte_stream.name}\"[{'Closed' if self.byte_stream.closed else self.Position()}]"
    
    def EnsureOpen(self):
        if self.byte_stream.closed: self.byte_stream = open(self.byte_stream.name, self.byte_stream.mode)
    def ReadBytes(self, count) -> bytes: return self.byte_stream.read(count)
    def Seek(self, offset, mode=io.SEEK_SET): self.byte_stream.seek(offset, mode)
    def Position(self): return self.byte_stream.tell()
    
    def ReadString(self, count, stopOnNull=False): return self.ReadBytes(count).decode('utf-8',errors='ignore').rstrip('\0')
    def ReadString16(self, count, stopOnNull=False):
        if stopOnNull:
            s = ""
            for i in range(2*count):
                char = self.ReadBytes(2)
                if char == b'\x00\x00': break
                s += char.decode('utf-16',errors='ignore')
            return s
        else: return self.ReadBytes(2*count).decode('utf-16',errors='ignore').rstrip('\0')
    
    def ReadBool(self): return self.ReadInt8() == 1

    def ReadInt8(self) -> int: return unpack('b',self.ReadBytes(1))[0]
    def ReadInt16(self) -> int: return unpack('h',self.ReadBytes(2))[0]
    def ReadInt32(self) -> int: return unpack('i',self.ReadBytes(4))[0]
    def ReadInt64(self) -> int: return unpack('q',self.ReadBytes(8))[0]

    def ReadUInt8(self) -> int: return unpack('B',self.ReadBytes(1))[0]
    def ReadUInt16(self) -> int: return unpack('H',self.ReadBytes(2))[0]
    def ReadUInt32(self) -> int: return unpack('I',self.ReadBytes(4))[0]
    def ReadUInt64(self) -> int: return unpack('Q',self.ReadBytes(8))[0]

    def ReadFloat(self) -> float: return unpack('f',self.ReadBytes(4))[0]
    def ReadDouble(self) -> float: return unpack('d',self.ReadBytes(8))[0]
    def ReadStruct(self, format, count): return unpack(format,self.ReadBytes(count))

    def ReadIntBool(self): return self.ReadInt32() == 1

    def ReadGuid(self): return uuid.UUID(bytes_le=self.ReadBytes(16))
    def ReadFString(self):
        length = self.ReadInt32()
        if length < 0: return self.ReadBytes(-2*length)[:-2].decode('utf-16')
        else: return self.ReadBytes(length)[:-1].decode('ascii')
    def ReadFName(self, names): return FName(self, names)

class FName:
    def __init__(self, f:ByteStream, names):
        i_name, self.i = (f.ReadInt32(), f.ReadInt32())
        self.str = names[i_name]
    def FullName(self) -> str: return f"{self.str}_{self.i - 1}" if self.i > 0 else self.str
    def __str__(self) -> str: return self.FullName()
    def __repr__(self) -> str: return str(self)
class FExpressionInput:
    def __init__(self, asset:UAsset, editor=True):
        self.node = asset.GetExport(asset.f.ReadInt32()) if editor else None
        self.node_output_i = asset.f.ReadInt32()
        self.input_name = asset.f.ReadFString()
        if editor:
            self.mask = asset.f.ReadInt32()
            self.mask_rgba = (asset.f.ReadInt32(),asset.f.ReadInt32(),asset.f.ReadInt32(),asset.f.ReadInt32())
    def __repr__(self) -> str: return f"{self.node}({self.node_output_i}) {self.input_name}(Mask={self.mask}, Mask RGBA={str(self.mask_rgba).replace(' ','')}"
class ArrayDesc:
    def __init__(self, f, b32=True):
        if b32: self.count, self.offset = (f.ReadInt32(), f.ReadInt32())
        else: self.count, self.offset = (f.ReadInt64(), f.ReadInt64())
    def TrySeek(self, f:ByteStream) -> bool:
        valid = self.offset > 0 and self.count > 0
        if valid: f.Seek(self.offset)
        return valid
    def __repr__(self) -> str: return f"{self.offset}[{self.count}]"
class EngineVersion:
    def __init__(self, major, minor, patch, changelist, branch):
        self.major = major
        self.minor = minor
        self.patch = patch
        self.changelist = changelist
        self.branch = branch
    def Read(f): return EngineVersion(f.ReadUInt16(), f.ReadUInt16(), f.ReadUInt16(), f.ReadUInt32(), f.ReadFString())
class Import: #FObjectImport
    def __init__(self, asset:UAsset, editor=True): # ObjectResource.cpp
        self.class_package = asset.f.ReadFName(asset.names).str
        self.class_name = asset.f.ReadFName(asset.names).str
        self.outer_index = asset.f.ReadInt32() # TODO: don't store
        self.object_name = asset.f.ReadFName(asset.names)
        if editor and asset.version_ue4 >= 520: self.package_name = asset.f.ReadFName(asset.names)
        self.asset = asset
    @property
    def import_ref(self): return self.asset.TryGetImport(self.outer_index)
    def __repr__(self) -> str: return f"{self.object_name}({self.class_package}.{self.class_name})"
class Export: #FObjectExport
    def __init__(self, asset:UAsset):
        self.asset = asset
        f = asset.f
        class_index, super_index = (f.ReadInt32(), f.ReadInt32())
        if asset.version_ue4 >= 508: template_index = f.ReadInt32()
        self.outer_index = f.ReadInt32()
        self.object_name = f.ReadFName(asset.names)
        self.object_flags = f.ReadUInt32()
        self.serial_desc = ArrayDesc(f, asset.version_ue4 < 511)
        force_export, not_for_client, not_for_server = (f.ReadIntBool(), f.ReadIntBool(), f.ReadIntBool())
        self.package_guid = f.ReadGuid()
        package_flags = f.ReadUInt32()
        if asset.version_ue4 >= 365: not_always_loaded_for_editor = f.ReadIntBool()
        if asset.version_ue4 >= 465: self.is_asset = f.ReadIntBool()
        if asset.version_ue4 >= 507:
            export_depends_offset = f.ReadInt32()
            ser_before_ser_depends_size = f.ReadInt32()
            create_before_ser_depends_size = f.ReadInt32()
            ser_before_create_depends_size = f.ReadInt32()
            create_before_create_depends_size = f.ReadInt32()
        
        self.properties = None
        self.export_class = asset.DecodePackageIndex(class_index)
        self.export_class_type = self.export_class.object_name.str if self.export_class else None
    def __repr__(self) -> str: return f"{self.object_name} [{len(self.properties) if self.properties != None else 'Unread'}]"
    def ReadProperties(self, read_children=True):
        if self.properties: return
        self.properties = Properties()

        if self.export_class_type == "Function" or self.export_class_type.endswith("BlueprintGeneratedClass"):
            print(f"Skipping Export \"{self.export_class_type}\"")
            return
        
        #self.asset.f.EnsureOpen()
        self.asset.f.Seek(self.serial_desc.offset)
        self.properties.Read(self.asset, read_children=read_children)

        #match export_class_type: case "Enum" | "UserDefinedEnum": export.enum = # TODO: post "normal export" data
        extras_len = (self.serial_desc.offset + self.serial_desc.count) - self.asset.f.Position()
        if extras_len < 0: raise
        else:
            self.extras = [x for x in self.asset.f.ReadBytes(extras_len)] if extras_len > 0 else None
            #match self.export_class_type:
                #case "ObjectProperty": # [0, i_exp(self), 1, 4, 4, 196, 0]
class Properties(dict):
    def Read(self, asset:UAsset, header=True, read_children=True):
        while True:
            prop = UProperty()
            if prop.TryRead(asset, header, read_children): self[prop.name] = prop
            else: break
    def TryGetValue(self, key:str, default=None):
        property = self.get(key)
        return property.value if property else default
class UProperty:
    def __repr__(self) -> str: return f"{self.name}({self.struct_type if hasattr(self,'struct_type') else self.type}) = {self.value}"
    def TryRead(self, asset:UAsset, header=True, read_children=True):
        f = asset.f
        self.name = f.ReadFName(asset.names).FullName()
        if self.name == "None": return None

        self.type = f.ReadFName(asset.names).str
        self.len = f.ReadInt32()
        self.i_dupe = f.ReadInt32()
        
        return self.TryReadData(asset, header, read_children)
    def TryReadData(self, asset:UAsset, header=True, read_children=True):
        if self.type == "None": raise
        f = asset.f
        
        match self.type:
            case "StructProperty":
                if header:
                    self.struct_type = f.ReadFName(asset.names).str
                    if asset.version_ue4 >= 441: self.struct_guid = f.ReadGuid()
                    self.guid = asset.TryReadPropertyGuid()

                header = False
                p = f.Position()
                match self.struct_type:
                    case "Guid": self.value = f.ReadGuid()
                    case "Vector" | "Rotator":
                        if header: self.guid = asset.TryReadPropertyGuid()
                        self.value = (f.ReadFloat(), f.ReadFloat(), f.ReadFloat())
                    case "Color":
                        if header: self.guid = asset.TryReadPropertyGuid()
                        bgra = f.ReadBytes(4)
                        self.value = (bgra[2],bgra[1],bgra[0],bgra[3]) # RGBA
                    case "LinearColor":
                        if header: self.guid = asset.TryReadPropertyGuid()
                        self.value = (f.ReadFloat(), f.ReadFloat(), f.ReadFloat(), f.ReadFloat()) # RGBA
                    case "ColorMaterialInput" | "ScalarMaterialInput" | "VectorMaterialInput":
                        p = f.Position()
                        self.value = asset.GetExport(f.ReadInt32())# TODO: other data is default value?
                        f.Seek(p + self.len)
                    case "ExpressionInput": self.value = FExpressionInput(asset)
                    case "ExpressionOutput": self.value = Properties().Read(asset)
                    case "StreamingTextureBuildInfo": self.value = [x for x in f.ReadBytes(self.len)]
                    case _:
                        self.value = [x for x in f.ReadBytes(self.len)]
                        if logging: print(f"Uknown Struct Type \"{self.struct_type}\"")
                        #raise Exception(f"Uknown Struct Type \"{struct_type}\"")
                p_diff = f.Position() - (p + self.len)
                if p_diff != 0:
                    f.Seek(p)
                    self.raw = [x for x in f.ReadBytes(self.len)]
                    if logging: print(f"Length Mismatch! {self.struct_type} : {p_diff}")
                
                if self.len == 0: raise
            case "ArrayProperty":
                if header:
                    self.array_type = f.ReadFName(asset.names).str
                    self.guid = asset.TryReadPropertyGuid()
                element_count = f.ReadInt32()
                if self.array_type == "StructProperty":
                    if asset.version_ue4 >= 500:
                        self.array_name = f.ReadFName(asset.names).FullName()
                        if self.array_name == "None": raise
                        self.array_el_type = f.ReadFName(asset.names).str
                        if self.array_el_type == "None": raise
                        if self.array_type != self.array_el_type: raise
                        self.array_size = f.ReadInt64()
                        self.array_el_full_type = f.ReadFName(asset.names).str
                        self.struct_guid = f.ReadGuid()
                        self.guid = asset.TryReadPropertyGuid()
                    else: raise

                    if element_count == 0: raise
                    else:
                        self.value = []
                        next = f.Position() + self.array_size
                        try:
                            element_size = int(self.array_size / element_count)
                            single_prop = self.array_el_full_type not in ("FunctionExpressionInput","FunctionExpressionOutput")
                            for i in range(element_count):
                                prop = UProperty()
                                if single_prop:
                                    prop.name, prop.type, prop.struct_type, prop.len = ("", self.array_el_type, self.array_el_full_type, element_size)
                                    if prop.TryReadData(asset, False, read_children): self.value.append(prop)
                                else:
                                    self.value.append(Properties().Read(asset))
                        #except: pass
                        finally:
                            p_diff = next - f.Position()
                            if p_diff != 0:
                                f.Seek(next)
                                if logging: print(f"{self.array_name} Array Position Mismatch: {p_diff}")
                else:
                    self.value = []
                    #size_1 = int(self.len / element_count)
                    size_2 = int((self.len - 4) / element_count)
                    for i in range(element_count):
                        prop = UProperty()
                        prop.name, prop.type, prop.len = ("", self.array_type, size_2)
                        if prop.TryReadData(asset, False, read_children): self.value.append(prop)
            case "StrProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadFString()
            case "NameProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadFName(asset.names).FullName()
            case "ObjectProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = asset.DecodePackageIndex(f.ReadInt32())
                if read_children and self.value and type(self.value) is Export:
                    p = f.Position()
                    self.value.ReadProperties()
                    f.Seek(p)
            case "BoolProperty":
                self.value = f.ReadBool()
                if header: self.guid = asset.TryReadPropertyGuid()
            case "ByteProperty":
                if header:
                    self.enum_type = f.ReadFName(asset.names).str
                    self.guid = asset.TryReadPropertyGuid()
                match self.len:
                    case 1: self.value = f.ReadUInt8()
                    case 8: self.value = f.ReadFName(asset.names).FullName()
                    case _: raise
            case "Int8Property" | "Int16Property" | "IntProperty" | "Int64Property":
                if header: self.guid = asset.TryReadPropertyGuid()
                match self.len:
                    case 1: self.value = f.ReadInt8()
                    case 2: self.value = f.ReadInt16()
                    case 4: self.value = f.ReadInt32()
                    case 8: self.value = f.ReadInt64()
            case "UInt16Property" | "UInt32Property" | "UInt64Property": # TODO: UInt8?
                if header: self.guid = asset.TryReadPropertyGuid()
                match self.len:
                    case 2: self.value = f.ReadUInt16()
                    case 4: self.value = f.ReadUInt32()
                    case 8: self.value = f.ReadUInt64()
            case "FloatProperty" | "DoubleProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                match self.len:
                    case 4: self.value = f.ReadFloat()
                    case 8: self.value = f.ReadDouble()
            case "EnumProperty":
                if header:
                    self.enum_type = f.ReadFName(asset.names).str
                    self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadFName(asset.names).FullName()
            case "TextProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = [x for x in f.ReadBytes(self.len)]
            case "MulticastDelegateProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = []
                for i in range(f.ReadInt32()): self.value.append((f.ReadInt32(), f.ReadFName(asset.names).FullName()))
            case "MulticastSparseDelegateProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = [x for x in f.ReadBytes(self.len)]
            case _: raise Exception(f"Uknown Property Type \"{self.type}\"")
        return True
class UAsset:
    def __init__(self, filepath): self.filepath = filepath
    def __repr__(self) -> str: return f"\"{self.f.byte_stream.name}\", {len(self.imports)} Imports, {len(self.exports)} Exports"
    def GetImport(self, i) -> Import: return self.imports[-i - 1]
    def GetExport(self, i) -> Export: return self.exports[i - 1]
    def TryGetImport(self, i) -> Export: return self.GetImport(i) if i < 0 else None
    def TryGetExport(self, i) -> Export: return self.GetExport(i) if i > 0 else None
    def DecodePackageIndex(self, i):
        if i < 0: return self.GetImport(i)
        elif i > 0: return self.GetExport(i)
        else: return None #raise Exception("Invalid Package Index of 0")
    def TryReadPropertyGuid(self) -> uuid.UUID: return self.f.ReadGuid() if self.version_ue4 >= 503 and self.f.ReadBool() else None
    def ReadHeader(self, editor=True): # UE4 PackageFileSummary.cpp
        f = self.f
        sig = f.ReadUInt32()
        if sig != 0x9E2A83C1: raise Exception(f"Unknown signature: {sig:X}")

        self.version_legacy = f.ReadInt32()
        if self.version_legacy != -4: self.version_legacy_ue3 = f.ReadInt32()
        self.version_ue4 = version_ue4 = f.ReadInt32()
        self.version_ue4_licensee = f.ReadInt32()
        if self.version_legacy < -2:
            self.custom_versions = []
            for i in range(f.ReadInt32()): # TODO
                custom_version_guid, custom_version = (f.ReadGuid(), f.ReadInt32())
                self.custom_versions.append((custom_version_guid, custom_version))
        
        self.header_size = f.ReadInt32()
        self.folder_name = f.ReadFString()
        package_flags = f.ReadUInt32()
        self.names_desc = ArrayDesc(f)
        if version_ue4 >= 516: localization_id = f.ReadFString()
        if version_ue4 >= 459: gatherable_text_desc = ArrayDesc(f)
        self.exports_desc = ArrayDesc(f)
        self.imports_desc = ArrayDesc(f)
        self.depends_offset = f.ReadInt32()
        if version_ue4 >= 384: self.soft_pkg_refs_desc = ArrayDesc(f)
        if version_ue4 >= 510: self.searchable_names_desc_offset = f.ReadInt32()
        thumbnail_table_offset = f.ReadInt32()
        self.package_guid = f.ReadGuid()
        if editor:
            if version_ue4 >= 518:
                persistent_guid = f.ReadGuid()
                if version_ue4 < 520: owner_persistent_guid = f.ReadGuid()
        generation_count = f.ReadInt32()
        if generation_count < 0: raise
        for i in range(generation_count): gen_export_count, get_name_count = (f.ReadInt32(), f.ReadInt32())
        engine_version = EngineVersion.Read(f) if version_ue4 >= 336 else EngineVersion(4,0,0,f.ReadUInt32(),"")
        compatible_version = EngineVersion.Read(f) if version_ue4 >= 444 else engine_version
        compression_flags = f.ReadUInt32()
        compressed_chunks_count = f.ReadInt32()
        if compressed_chunks_count > 0: raise Exception("Asset has package-level compression and is likely too old to be parsed")
        package_source = f.ReadUInt32()
        for i in range(f.ReadInt32()): self.package = f.ReadFString()
        if self.version_legacy > -7:
            texture_alloc_count = f.ReadInt32()
            if texture_alloc_count > 0: raise Exception("Asset has texture allocation info and is likely too old to be parsed")
        asset_registry_data_offset = f.ReadInt32()
        bulk_data_offset = f.ReadInt64()
        world_tile_info_data_offset = f.ReadInt32() if version_ue4 >= 224 else 0
        if version_ue4 >= 326:
            for i in range(f.ReadInt32()): chunk_id = f.ReadInt32()
        elif version_ue4 >= 278: chunk_id = f.ReadInt32()
        if version_ue4 >= 507: self.preload_depends_desc = ArrayDesc(f)
    def ReadProperties(self):
        if self.header_size > 0 and self.exports_desc.count > 0:
            for i in range(self.exports_desc.count):
                self.exports[i].ReadProperties()
            self.f.byte_stream.close()
    def Read(self, read_properties=True): # PackageReader.cpp
        t0 = time.time()
        self.f = ByteStream(open(self.filepath, 'rb'))
        self.ReadHeader()
        
        self.names:list[str] = []
        if self.names_desc.TrySeek(self.f):
            for i in range(self.names_desc.count):
                name = self.f.ReadFString()
                self.names.append(name)
                if self.version_ue4 >= 504 and name != "": hash = self.f.ReadUInt32()
        
        self.imports:list[Import] = []
        if self.imports_desc.TrySeek(self.f):
            for i in range(self.imports_desc.count): self.imports.append(Import(self))
        
        self.exports:list[Export] = []
        if self.exports_desc.TrySeek(self.f):
            for i in range(self.exports_desc.count): self.exports.append(Export(self))

        if read_properties:
            self.ReadProperties()
            print(f"Imported {self} in {time.time() - t0:.2f}s")
    def Close(self): self.f.byte_stream.close()
    def __enter__(self):
        self.Read(False)
        return self
    def __exit__(self, *args): self.Close()

def ArchiveToProjectPath(path): return os.path.join(project_dir, "Content", str(pathlib.Path(path).relative_to("\\Game"))) + ".uasset"



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

def DeDuplicateName(name):
    i = name.rfind('.')
    return name[:i] if i >= 0 else name
def GuessBaseDir(filename): return filename[:filename.find("Game")] # Unreal defaults to starting path with "Game" on asset export
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
def SetPos(node, param_x, param_y, params): node.location = (int(params.get(param_x,"0")), -int(params.get(param_y,"0")))
def ImportUMaterial(filepath):
    t0 = time.time()
    if logging: print(f"Import \"{filepath}\"")

    with UAsset(filepath) as asset: asset.ReadProperties()# TODO: lazy faster?

    mat = None
    mat_name = None

    for exp in asset.exports:
        match exp.export_class_type:
            case 'Material':
                mat_name = exp.object_name.FullName()
                mat = bpy.data.materials.new(mat_name)

    
    if logging: print(f"Imported {mat_name}: {(time.time() - t0) * 1000:.2f}ms")
    #return (mat, graph_data)
    return mat

ImportUMaterial(filepath)
print("Done")