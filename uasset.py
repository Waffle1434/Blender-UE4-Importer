from __future__ import annotations
import io, uuid, time, os, glob, json, winreg
from struct import *
from ctypes import *
from mathutils import *

logging = True
try_unknown_structs = False

class ByteStream:
    def __init__(self, byte_stream:io.BufferedReader): self.byte_stream = byte_stream
    def __repr__(self) -> str: return f"\"{self.byte_stream.name}\"[{'Closed' if self.byte_stream.closed else self.Position()}]"
    
    def EnsureOpen(self):
        if self.byte_stream.closed: self.byte_stream = open(self.byte_stream.name, self.byte_stream.mode)
    def ReadBytes(self, count) -> bytes: return self.byte_stream.read(count)
    def Seek(self, offset, mode=io.SEEK_SET): self.byte_stream.seek(offset, mode)
    def Position(self): return self.byte_stream.tell()
    
    def ReadString(self, count, stopOnNull=False): return self.byte_stream.read(count).decode('utf-8',errors='ignore').rstrip('\0')
    def ReadString16(self, count, stopOnNull=False):
        if stopOnNull:
            s = ""
            for i in range(2*count):
                char = self.byte_stream.read(2)
                if char == b'\x00\x00': break
                s += char.decode('utf-16',errors='ignore')
            return s
        else: return self.byte_stream.read(2*count).decode('utf-16',errors='ignore').rstrip('\0')
    
    def ReadBool(self): return unpack('?',self.byte_stream.read(1))[0]
    def ReadBool32(self): return self.ReadInt32() == 1

    def ReadInt8(self) -> int: return unpack('b',self.byte_stream.read(1))[0]
    def ReadInt16(self) -> int: return unpack('h',self.byte_stream.read(2))[0]
    def ReadInt32(self) -> int: return unpack('i',self.byte_stream.read(4))[0]
    def ReadInt64(self) -> int: return unpack('q',self.byte_stream.read(8))[0]

    def ReadUInt8(self) -> int: return unpack('B',self.byte_stream.read(1))[0]
    def ReadUInt16(self) -> int: return unpack('H',self.byte_stream.read(2))[0]
    def ReadUInt32(self) -> int: return unpack('I',self.byte_stream.read(4))[0]
    def ReadUInt64(self) -> int: return unpack('Q',self.byte_stream.read(8))[0]

    def ReadFloat(self) -> float: return unpack('f',self.byte_stream.read(4))[0]
    def ReadDouble(self) -> float: return unpack('d',self.byte_stream.read(8))[0]
    def ReadStruct(self, format:str, count): return unpack(format,self.byte_stream.read(count))

    def ReadIntBool(self): return self.ReadInt32() == 1

    def ReadStructure(self, ty:Structure): return ty.from_buffer_copy(self.byte_stream.read(sizeof(ty)))
    def ReadArray(self, ty:Structure) -> list: return self.ReadStructure(ty * self.ReadInt32())
    def ReadBulkArray(self, ty:Structure) -> list:
        el_size = self.ReadInt32()
        return self.ReadArray(ty)
    def SkipArray(self, ty:Structure): self.Seek(sizeof(ty) * self.ReadInt32(), io.SEEK_CUR)
    def ReadGuid(self): return uuid.UUID(bytes_le=self.byte_stream.read(16))
    def ReadFString(self):
        length = self.ReadInt32()
        if length < 0: return self.byte_stream.read(-2*length)[:-2].decode('utf-16')
        else: return self.byte_stream.read(length)[:-1].decode('ascii')
    def ReadFName(self, names):
        i_name, i = unpack('ii',self.byte_stream.read(8))
        fn = names[i_name]
        return f"{fn}_{i - 1}" if i > 0 else fn
def StructToString(struct, names=True):
    structStr = ""
    comma = False
    for name, ty in struct._fields_:
        if comma: structStr += ", "
        else: comma = True
        if names: structStr += f"{name}: "
        val = getattr(struct, name)
        structStr += f'{val:.2f}' if ty == c_float else str(val)
    return f"({structStr})"
class PrintableStruct(Structure):
    _pack_ = 1
    def __str__(self): return StructToString(self)
    def __repr__(self): return str(self)

class FExpressionInput:
    def __init__(self, asset:UAsset, editor=True):
        self.node = asset.GetExport(asset.f.ReadInt32()) if editor else None
        self.node_output_i = asset.f.ReadInt32()
        self.input_name = asset.f.ReadFName(asset.names) if asset.summary.version_ue4 >= 514 else asset.f.ReadFString()
        if editor:
            self.mask = asset.f.ReadInt32()
            self.mask_rgba = (asset.f.ReadInt32(),asset.f.ReadInt32(),asset.f.ReadInt32(),asset.f.ReadInt32())
    def __repr__(self) -> str: return f"{self.node}({self.node_output_i}) {self.input_name}(Mask={self.mask}, Mask RGBA={str(self.mask_rgba).replace(' ','')}"
class FVector2D(PrintableStruct):
    _fields_ = ( ('x', c_float), ('y', c_float) )
    def __str__(self): return StructToString(self, False)
    def ToTuple(self): return (self.x, self.y)
class FVector(PrintableStruct):
    _fields_ = ( ('x', c_float), ('y', c_float), ('z', c_float) )
    def __str__(self): return StructToString(self, False)
    def ToVector(self): return Vector((self.x, self.y, self.z))
    def ToVectorPos(self): return Vector((self.y, self.x, self.z))
class FVector4(PrintableStruct):
    _fields_ = ( ('x', c_float), ('y', c_float), ('z', c_float), ('w', c_float) )
    def __str__(self): return StructToString(self, False)
class FIntPoint(PrintableStruct): _fields_ = ( ('x', c_int), ('y', c_int) )
class FQuat(PrintableStruct):
    _fields_ = ( ('x', c_float), ('y', c_float), ('z', c_float), ('w', c_float) )
    def __str__(self): return StructToString(self, False)
class FTransform(PrintableStruct): _fields_ = ( ('rotation', FQuat), ('translation', FVector), ('scale', FVector) )
class FColor(PrintableStruct): _fields_ = ( ('b', c_ubyte), ('g', c_ubyte), ('r', c_ubyte), ('a', c_ubyte) )
class FLinearColor(PrintableStruct):
    _fields_ = ( ('r', c_float), ('g', c_float), ('b', c_float), ('a', c_float) )
    def ToTuple(self): return (self.r, self.g, self.b, self.a)
    def ToTupleRGB(self): return (self.r, self.g, self.b, 1)
class FBox(PrintableStruct): _fields_ = ( ('min', FVector), ('max', FVector), ('valid', c_ubyte) )
class FBoxSphereBounds(PrintableStruct): _fields_ = ( ('origin', FVector), ('box_extent', FVector), ('sphere_radius', c_float) )
class FMeshSectionInfo(PrintableStruct): _fields_ = ( ('material_index', c_int), ('collision', c_bool), ('shadow', c_bool) )
class FStripDataFlags(PrintableStruct):
    _fields_ = ( ('global_strip_flags', c_ubyte), ('class_strip_flags', c_ubyte) )
    def StripForServer(self): return self.global_strip_flags & 2 != 0
    def StripForEditor(self): return self.global_strip_flags & 1 != 0
    def StripClassData(self, flag): return self.class_strip_flags & flag != 0
#class TMapPair(PrintableStruct): _fields_ = ( ('key'), ('value') )

prop_table_types = { "ExpressionOutput", "ScalarParameterValue", "TextureParameterValue", "VectorParameterValue", "MaterialFunctionInfo", "StaticMaterial", "KAggregateGeom", "BodyInstance", 
                    "KConvexElem", "Transform", "StaticMeshSourceModel", "MeshBuildSettings", "MeshReductionSettings", "MeshUVChannelInfo", "AssetEditorOrbitCameraPosition", "SimpleMemberReference", 
                    "CollisionResponse", "ResponseChannel", "StreamingTextureBuildInfo", "BuilderPoly", "PostProcessSettings", "LevelViewportInfo", "MaterialProxySettings", "MeshProxySettings",
                    "MeshMergingSettings", "HierarchicalSimplification", "Timeline", "TimelineFloatTrack", "ParameterGroupData", "MaterialParameterInfo", "MaterialInstanceBasePropertyOverrides", 
                    "MaterialCachedExpressionData" }
prop_table_blacklist = { "MaterialTextureInfo" }
struct_map = { "Vector":FVector, "Rotator":FVector, "Vector4":FVector4, "IntPoint":FIntPoint, "Quat":FQuat, "Box":FBox, "Color":FColor, "LinearColor":FLinearColor, "BoxSphereBounds":FBoxSphereBounds }

class ArrayDesc:
    def __init__(self, f:ByteStream, b32=True):
        #if b32: self.count, self.offset = (f.ReadInt32(), f.ReadInt32())
        #else: self.count, self.offset = (f.ReadInt64(), f.ReadInt64())
        if b32: self.count, self.offset = f.ReadStruct("ii", 8)
        else: self.count, self.offset = f.ReadStruct("qq", 16)
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
        self.class_package = asset.f.ReadFName(asset.names)
        self.class_name = asset.f.ReadFName(asset.names)
        self.outer_index = asset.f.ReadInt32() # TODO: don't store
        self.object_name = asset.f.ReadFName(asset.names)
        if editor and asset.summary.version_ue4 >= 520: self.package_name = asset.f.ReadFName(asset.names)
        self.asset = asset
    @property
    def import_ref(self): return self.asset.TryGetImport(self.outer_index)
    def __repr__(self) -> str: return f"{self.object_name}({self.class_package}.{self.class_name})"
class Export: #FObjectExport
    def __init__(self, asset:UAsset):
        self.asset = asset
        f = asset.f
        self.class_index, self.super_index = f.ReadStruct('ii', 8)
        if asset.summary.version_ue4 >= 508: self.template_index = f.ReadInt32()
        self.outer_index = f.ReadInt32()
        self.object_name = f.ReadFName(asset.names)
        self.object_flags = f.ReadUInt32()
        self.serial_desc = ArrayDesc(f, asset.summary.version_ue4 < 511)
        self.force_export, self.not_for_client, self.not_for_server = f.ReadStruct('iii', 12)
        self.package_guid = f.ReadGuid()
        self.package_flags = f.ReadUInt32()
        if asset.summary.version_ue4 >= 365: self.not_always_loaded_for_editor = f.ReadIntBool()
        if asset.summary.version_ue4 >= 465: self.is_asset = f.ReadIntBool()
        if asset.summary.version_ue4 >= 507:
            f.Seek(20, io.SEEK_CUR)
            '''vals = f.ReadStruct('iiiii', 20)
            self.export_depends_offset = vals[0]
            self.ser_before_ser_depends_size = vals[1]
            self.create_before_ser_depends_size = vals[2]
            self.ser_before_create_depends_size = vals[3]
            self.create_before_create_depends_size = vals[4]'''
        
        self.properties = None
        self.export_class = asset.DecodePackageIndex(self.class_index)
        self.export_class_type = self.export_class.object_name if self.export_class else None
    def __repr__(self) -> str: return f"{self.object_name} [{len(self.properties) if self.properties != None else 'Unread'}]"
    def ReadProperties(self, read_children=True, read_extras=True):
        if self.properties: return
        self.properties = Properties()

        if self.export_class_type in ('Function', 'FbxStaticMeshImportData') or self.export_class_type.endswith("BlueprintGeneratedClass"):
            print(f"Skipping Export \"{self.export_class_type}\"")
            return
        
        #self.asset.f.EnsureOpen()
        self.asset.f.Seek(self.serial_desc.offset)
        self.properties.Read(self.asset, read_children=read_children)

        #match export_class_type: case "Enum" | "UserDefinedEnum": export.enum = # TODO: post "normal export" data
        extras_len = (self.serial_desc.offset + self.serial_desc.count) - self.asset.f.Position()
        assert extras_len >= 0
        if read_extras: self.extras = [x for x in self.asset.f.ReadBytes(extras_len)] if extras_len > 0 else None
class Properties(dict):
    def get(self, key:str, default=None) -> UProperty: return super().get(key, default)
    def Read(self, asset:UAsset, header=True, read_children=True):
        while True:
            prop = UProperty()
            if prop.TryRead(asset, header, read_children):
                existing_val = self.get(prop.name)
                if not existing_val: self[prop.name] = prop
                else:
                    if type(existing_val.value) != list: existing_val.value = [existing_val.value]
                    existing_val.value.append(prop.value)
            else: break
        return self
    def TryGetValue(self, key:str, default=None):
        property = self.get(key)
        return property.value if property else default
    def TryGetProperties(self, key:str):
        export:Export = self.TryGetValue(key)
        if export:
            export.ReadProperties(False, False)
            return export.properties
        return None
class UProperty:
    def __repr__(self) -> str: return f"{self.name}({self.struct_type if hasattr(self,'struct_type') else self.type}) = {self.value}"
    def TryRead(self, asset:UAsset, header=True, read_children=True):
        f = asset.f
        self.name = f.ReadFName(asset.names)
        if self.name == "None": return None

        self.type = f.ReadFName(asset.names)
        self.len = f.ReadInt32()
        self.i_dupe = f.ReadInt32()
        
        return self.TryReadData(asset, header, read_children)
    def TryReadData(self, asset:UAsset, header=True, read_children=True):
        assert self.type != "None"
        f = asset.f
        
        match self.type:
            case "StructProperty":
                if header:
                    self.struct_type = f.ReadFName(asset.names)
                    if asset.summary.version_ue4 >= 441: self.struct_guid = f.ReadGuid()
                    self.guid = asset.TryReadPropertyGuid()

                p = f.Position()
                match self.struct_type:
                    case "Guid": self.value = f.ReadGuid()
                    case "ExpressionInput": self.value = FExpressionInput(asset)
                    case "ColorMaterialInput" | "ScalarMaterialInput" | "VectorMaterialInput":
                        p = f.Position()
                        self.value = asset.GetExport(f.ReadInt32())# TODO: other data is default value?
                        f.Seek(p + self.len)
                    case _:
                        structure = struct_map.get(self.struct_type)
                        if structure: self.value = f.ReadStructure(structure)
                        elif self.struct_type in prop_table_types: self.value = Properties().Read(asset)
                        else:
                            load_raw = not try_unknown_structs
                            if try_unknown_structs:
                                p = f.Position()
                                try:
                                    self.value = Properties().Read(asset)
                                    if self.struct_type not in prop_table_blacklist and f.Position() - (p + self.len) == 0:
                                        prop_table_types.add(self.struct_type)
                                        if logging:
                                            print(f"Unknown Struct \"{self.struct_type}\" is probably a property table")
                                except Exception as e:
                                    print(f"{self.struct_type} Struct Error: {e}")
                                    f.Seek(p)
                                    load_raw = True
                                    pass
                            if load_raw:
                                self.value = [x for x in f.ReadBytes(self.len)]
                                if logging: print(f"Unknown Struct Type \"{self.struct_type}\"")
                p_diff = f.Position() - (p + self.len)
                if p_diff != 0:
                    f.Seek(p)
                    self.raw = [x for x in f.ReadBytes(self.len)]
                    if logging: print(f"Length Mismatch! {self.struct_type} : {p_diff}")
                
                assert self.len > 0
            case "ArrayProperty": # | "MapProperty":
                #if self.type == "MapProperty": f.ReadBytes(8)

                if header:
                    self.array_type = f.ReadFName(asset.names)
                    self.guid = asset.TryReadPropertyGuid()
                element_count = f.ReadInt32()
                if self.array_type == "StructProperty":
                    if asset.summary.version_ue4 >= 500:
                        self.array_name = f.ReadFName(asset.names)
                        assert self.array_name != "None"
                        self.array_el_type = f.ReadFName(asset.names)
                        assert self.array_el_type != "None"
                        assert self.array_type == self.array_el_type
                        self.array_size = f.ReadInt64()
                        self.array_el_full_type = f.ReadFName(asset.names)
                        self.struct_guid = f.ReadGuid()
                        self.guid = asset.TryReadPropertyGuid()
                    else: raise

                    assert element_count > 0
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
            case "MapProperty":
                #if header: self.guid = asset.TryReadPropertyGuid()
                self.value = [x for x in f.ReadBytes(self.len)]
                #print("!")
                if header:
                    self.key_type = f.ReadFName(asset.names)
                    self.value_type = f.ReadFName(asset.names)
            case "StrProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadFString()
            case "NameProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadFName(asset.names)
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
                    self.enum_type = f.ReadFName(asset.names)
                    self.guid = asset.TryReadPropertyGuid()
                match self.len:
                    case 1: self.value = f.ReadUInt8()
                    case 8: self.value = f.ReadFName(asset.names)
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
                    self.enum_type = f.ReadFName(asset.names)
                    self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadFName(asset.names)
            case "MulticastDelegateProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = []
                for i in range(f.ReadInt32()): self.value.append((f.ReadInt32(), f.ReadFName(asset.names)))
            case "TextProperty" | "MulticastSparseDelegateProperty" | "DelegateProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = [x for x in f.ReadBytes(self.len)]
            case _: raise Exception(f"Uknown Property Type \"{self.type}\"")
        return True
class USummary:
    def __init__(self, asset:UAsset, editor=True): # UE4 PackageFileSummary.cpp
        f = asset.f
        sig = f.ReadUInt32()
        if sig != 0x9E2A83C1: raise Exception(f"Unknown signature: {sig:X}")

        self.version_legacy = f.ReadInt32()
        if self.version_legacy != -4: self.version_legacy_ue3 = f.ReadInt32()
        self.version_ue4 = version_ue4 = f.ReadInt32()
        self.version_ue4_licensee = f.ReadInt32()
        if self.version_legacy < -2:
            self.custom_versions = {}
            for i in range(f.ReadInt32()):
                guid, version = (f.ReadGuid(), f.ReadInt32())
                self.custom_versions[guid] = version
        self.header_size = f.ReadInt32()
        self.folder_name = f.ReadFString()
        self.package_flags = f.ReadUInt32()
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
        assert generation_count >= 0
        for i in range(generation_count): gen_export_count, get_name_count = (f.ReadInt32(), f.ReadInt32())
        engine_version = EngineVersion.Read(f) if version_ue4 >= 336 else EngineVersion(4,0,0,f.ReadUInt32(),"")
        self.compatible_version = EngineVersion.Read(f) if version_ue4 >= 444 else engine_version
        self.compression_flags = f.ReadUInt32()
        compressed_chunks_count = f.ReadInt32()
        if compressed_chunks_count > 0: raise Exception("Asset has package-level compression and is likely too old to be parsed")
        self.package_source = f.ReadUInt32()
        for i in range(f.ReadInt32()): self.package = f.ReadFString()
        if self.version_legacy > -7:
            texture_alloc_count = f.ReadInt32()
            if texture_alloc_count > 0: raise Exception("Asset has texture allocation info and is likely too old to be parsed")
        self.asset_registry_data_offset = f.ReadInt32()
        self.bulk_data_offset = f.ReadInt64()
        self.world_tile_info_data_offset = f.ReadInt32() if version_ue4 >= 224 else 0
        if version_ue4 >= 326:
            for i in range(f.ReadInt32()): chunk_id = f.ReadInt32()
        elif version_ue4 >= 278: chunk_id = f.ReadInt32()
        if version_ue4 >= 507: self.preload_depends_desc = ArrayDesc(f)
class UProject:
    def __init__(self, uasset_path:str):
        self.dir = os.path.normpath(uasset_path[:uasset_path.find("\\Content\\")])
        uproject_file = next(glob.iglob(f'{self.dir}\\*.uproject'), None)
        if uproject_file:
            with open(uproject_file, 'r') as file: engine_version = json.load(file)['EngineAssociation']
            self.engine_dir = winreg.QueryValueEx(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\EpicGames\Unreal Engine\{engine_version}"), "InstalledDirectory")[0] + "\\Engine\\"
        else: self.engine_dir = self.dir
class UAsset:
    def __init__(self, filepath:str, read_all=False, uproject=None):
        self.filepath = filepath
        if uproject: self.uproject = uproject
        else: self.uproject = UProject(filepath)
        self.extract_dir = os.path.join(self.uproject.dir, "Export")
        self.read_all = read_all
    def __repr__(self) -> str: return f"\"{self.f.byte_stream.name}\", {len(self.imports)} Imports, {len(self.exports)} Exports"
    def GetImport(self, i) -> Import: return self.imports[-i - 1]
    def GetExport(self, i) -> Export: return self.exports[i - 1]
    def TryGetImport(self, i): return self.GetImport(i) if i < 0 else None
    def TryGetExport(self, i): return self.GetExport(i) if i > 0 else None
    def DecodePackageIndex(self, i):
        if i < 0: return self.GetImport(i)
        elif i > 0: return self.GetExport(i)
        else: return None #raise Exception("Invalid Package Index of 0")
    def ToProjectPath(self, path:str):
        if path.startswith("/Game/"): return os.path.join(self.uproject.dir, "Content", path[6:]) + ".uasset"
        elif path.startswith("/Engine/"): return os.path.join(self.uproject.engine_dir, "Content", path[8:]) + ".uasset"
        else: raise
        
    def TryReadPropertyGuid(self) -> uuid.UUID: return self.f.ReadGuid() if self.summary.version_ue4 >= 503 and self.f.ReadBool() else None
    #def TryReadProperty(self): # TODO
    def Read(self, read_all=True, log=False): # PackageReader.cpp
        t0 = time.time()
        self.f = ByteStream(open(self.filepath, 'rb'))
        self.summary = summary = USummary(self)

        self.names:list[str] = []
        if summary.names_desc.TrySeek(self.f):
            for i in range(summary.names_desc.count):
                name = self.f.ReadFString()
                self.names.append(name)
                if summary.version_ue4 >= 504 and name != "": hash = self.f.ReadUInt32()
        
        self.imports:list[Import] = []
        if summary.imports_desc.TrySeek(self.f):
            for i in range(summary.imports_desc.count): self.imports.append(Import(self))
        
        self.exports:list[Export] = []
        if summary.exports_desc.TrySeek(self.f):
            for i in range(summary.exports_desc.count): self.exports.append(Export(self))

        if read_all and summary.header_size > 0 and summary.exports_desc.count > 0:
            for export in self.exports: export.ReadProperties(False)
            self.f.byte_stream.close()
            if log: print(f"Imported {self} in {time.time() - t0:.2f}s")
    def Close(self): self.f.byte_stream.close()
    def __enter__(self):
        self.Read(self.read_all)
        return self
    def __exit__(self, *args): self.Close()

if __name__ != "uasset":
    #asset = UAsset(r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Materials\M_Base_Trim.uasset")
    #asset = UAsset(r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Maps\Example_Stationary.umap")
    #asset = UAsset(r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Meshes\SM_Door_Small_A.uasset")
    #asset = UAsset(r"C:\Users\jdeacutis\Desktop\fSpy\New folder\Blender-UE4-Importer\Samples\SM_Door_Small_A.uasset")
    #asset.Read(False)
    #LoadUAssetScene(filepath)

    #sm = asset.exports[5]
    #sm.ReadProperties()

    print("Done")