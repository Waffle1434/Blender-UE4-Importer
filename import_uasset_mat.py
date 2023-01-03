from __future__ import annotations
import bpy, io, uuid, time, os, pathlib, subprocess
from struct import *
from mathutils import *

#filepath = r"F:\Art\Assets\Game\Blender UE4 Importer\Samples\M_Base_Trim.uasset"
filepath = r"F:\Art\Assets\Game\Blender UE4 Importer\Samples\MI_Trim_A_Red2.uasset"
#filepath = r"C:\Users\jdeacutis\Desktop\fSpy\New folder\Blender-UE4-Importer\Samples\M_Base_Trim.uasset"
exported_base_dir = r"F:\Art\Assets"
project_dir = r"F:\Projects\Unreal Projects\Assets"
#umodel_path = r"C:\Users\jdeacutis\Desktop\fSpy\New folder\Blender-UE4-Importer\umodel.exe"
umodel_path = r"F:\Art\Assets\Game\Blender UE4 Importer\umodel.exe"

logging = True
mute_ior = True
mute_fresnel = True

exported_base_dir = os.path.normpath(exported_base_dir)
project_dir = os.path.normpath(project_dir)
extract_dir = os.path.join(project_dir, "Export")
extracted_imports = {}

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
class Properties(dict):
    def Read(self, asset:UAsset, header=True, read_children=True):
        while True:
            prop = UProperty()
            if prop.TryRead(asset, header, read_children): self[prop.name] = prop
            else: break
        return self
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
                    case "ExpressionOutput" | "ScalarParameterValue" | "TextureParameterValue" | "VectorParameterValue": self.value = Properties().Read(asset)
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
def TryGetExtractedImport(imp:Import, extract_dir):
    archive_path = imp.import_ref.object_name.str
    extracted = extracted_imports.get(archive_path)
    if not extracted:
        match imp.class_name: # TODO: unify
            case 'StaticMesh': extension = "gltf"
            case 'Texture2D': extension = "png"
            case _: raise
        extracted_path = os.path.normpath(extract_dir + archive_path + f".{extension}")
        if not os.path.exists(extracted_path):
            asset_path = ArchiveToProjectPath(archive_path)
            extract_dir = os.path.join(extract_dir, "Game")
            subprocess.run(f"\"{umodel_path}\" -export -{extension} -out=\"{extract_dir}\" \"{asset_path}\"")
        match imp.class_name:
            case 'StaticMesh': raise #bpy.ops.import_scene.gltf(filepath=extracted_path, merge_vertices=True, import_pack_images=False)
            case 'Texture2D': extracted = bpy.data.images.load(extracted_path, check_existing=True)
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
def CreateNode(exp:Export, mat, nodes_data, graph_data, mat_object):
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
                node.inputs['RGB'].default_value = value
                node.inputs['A'].default_value = value[3]
            case 'MaterialExpressionStaticSwitchParameter':
                node.inputs['Fac'].default_value = 1 if value else 0
    match classname:
        case 'MaterialExpressionTextureCoordinate':
            uv_i = params.TryGetValue('CoordinateIndex')
            if uv_i != None:
                if mat_object == None: mat_object = bpy.context.object # TODO: less fragile?
                node.uv_map = mat_object.data.uv_layers.keys()[uv_i]
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
def ImportUMaterial(filepath, mat_name=None, mat_object=None): # TODO: return asset
    t0 = time.time()
    if logging: print(f"Import \"{filepath}\"")

    with UAsset(filepath) as asset: asset.ReadProperties()# TODO: lazy faster? (probably not)

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

                for exr_exp in params.TryGetValue('Expressions', ()): CreateNode(exr_exp.value, mat, nodes_data, graph_data, mat_object)
                for comment_exp in params.TryGetValue('EditorComments', ()):
                    comment_node = CreateNode(comment_exp.value, mat, nodes_data, graph_data, mat_object).node
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
                mat, graph_data = ImportUMaterial(mat_path, mat_name, mat_object) # TODO: handle not found

                for param in params.TryGetValue('ScalarParameterValues', ()):
                    node_data = graph_data.node_guids.get(param.value.TryGetValue('ExpressionGUID'))
                    if node_data: node_data.node.outputs[0].default_value = param.value.TryGetValue('ParameterValue')
                for param in params.TryGetValue('VectorParameterValues', ()):
                    node_data = graph_data.node_guids.get(param.value.TryGetValue('ExpressionGUID'))
                    if node_data:
                        node, value = (node_data.node, param.value.TryGetValue('ParameterValue'))
                        node.inputs['RGB'].default_value = value
                        node.inputs['A'].default_value = value[3]
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

for mat in bpy.data.materials: bpy.data.materials.remove(mat)
ImportUMaterial(filepath)
print("Done")