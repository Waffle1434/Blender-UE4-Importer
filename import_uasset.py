from __future__ import annotations
import bpy, io, uuid
from struct import *

#filepath = r"F:\Art\Assets\Game\Blender UE4 Importer\M_Base_Trim.uasset"
#filepath = r"F:\Art\Assets\Game\Blender UE4 Importer\Example_Stationary.umap"
#filepath = r"C:\Users\jdeacutis\Desktop\fSpy\New folder\Blender-UE4-Importer\M_Base_Trim.uasset"
filepath = r"C:\Users\jdeacutis\Desktop\fSpy\New folder\Blender-UE4-Importer\Example_Stationary.umap"

separate_bulkdata_files = False

class ByteStream:
    def __init__(self, byte_stream:io.BufferedReader):
        self.byte_stream = byte_stream
    
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
        self.input_i = asset.f.ReadInt32()
        if editor:
            self.mask = asset.f.ReadInt32()
            self.mask_rgba = (asset.f.ReadInt32(),asset.f.ReadInt32(),asset.f.ReadInt32(),asset.f.ReadInt32())
    def __repr__(self) -> str: return f"{self.node}({self.node_output_i}) (Mask={self.mask}, Mask RGBA={str(self.mask_rgba).replace(' ','')}"
class ArrayDesc:
    def __init__(self, f, b32=True):
        if b32: self.count, self.offset = (f.ReadInt32(), f.ReadInt32())
        else: self.count, self.offset = (f.ReadInt64(), f.ReadInt64())
    def __repr__(self) -> str: return f"{self.offset}[{self.count}]"
class EngineVersion:
    def __init__(self, major, minor, patch, changelist, branch):
        self.major = major
        self.minor = minor
        self.patch = patch
        self.changelist = changelist
        self.branch = branch
    def Read(f): return EngineVersion(f.ReadUInt16(), f.ReadUInt16(), f.ReadUInt16(), f.ReadUInt32(), f.ReadFString())
class Import:
    def __init__(self, f:ByteStream, names):
        self.class_package = f.ReadFName(names).str
        self.class_name = f.ReadFName(names).str
        self.outer_index = f.ReadInt32()
        self.object_name = f.ReadFName(names)
    def __repr__(self) -> str: return f"{self.object_name}({self.class_package}.{self.class_name})"
class Export:
    def __init__(self, f:ByteStream, asset:UAsset):
        self.class_index, self.super_index = (f.ReadInt32(), f.ReadInt32())
        if asset.version_ue4 >= 508: self.template_index = f.ReadInt32()
        self.outer_index = f.ReadInt32()
        self.object_name = f.ReadFName(asset.names)
        self.object_flags = f.ReadUInt32()
        self.serial_desc = ArrayDesc(f, asset.version_ue4 < 511)
        self.force_export, self.not_for_client, self.not_for_server = (f.ReadIntBool(), f.ReadIntBool(), f.ReadIntBool())
        self.package_guid = f.ReadGuid()
        self.package_flags = f.ReadUInt32()
        if asset.version_ue4 >= 365: self.not_always_loaded_for_editor = f.ReadIntBool()
        if asset.version_ue4 >= 465: self.is_asset = f.ReadIntBool()
        if asset.version_ue4 >= 507:
            self.export_depends_offset = f.ReadInt32()
            self.ser_before_ser_depends_size = f.ReadInt32()
            self.create_before_ser_depends_size = f.ReadInt32()
            self.ser_before_create_depends_size = f.ReadInt32()
            self.create_before_create_depends_size = f.ReadInt32()
        self.properties = []
    def __repr__(self) -> str: return f"{self.object_name} [{len(self.properties)}]"
class UAsset:
    def GetImport(self, i) -> Import: return self.imports[-i - 1]
    def GetExport(self, i) -> Export: return self.exports[i - 1]
    def TryGetImport(self, i) -> Export: return self.GetImport(i) if i < 0 else None
    def TryGetExport(self, i) -> Export: return self.GetExport(i) if i > 0 else None
    def DecodePackageIndex(self, i):
        if i < 0: return self.GetImport(i)
        elif i > 0: return self.GetExport(i)
        else: raise Exception("Invalid Package Index of 0")
    def TryReadPropertyGuid(self) -> uuid.UUID: return self.f.ReadGuid() if self.version_ue4 >= 503 and self.f.ReadBool() else None
    #def TryReadProperty(self): # TODO

    def __init__(self, filepath):
        with open(filepath, 'rb') as file:
            self.f = f = ByteStream(file)
            sig = f.ReadUInt32()
            if sig != 0x9E2A83C1: raise Exception(f"Unknown signature: {sig:X}")

            version_legacy = f.ReadInt32()
            if version_legacy != -4: version_legacy_ue3 = f.ReadInt32()
            self.version_ue4 = version_ue4 = f.ReadInt32()
            version_ue4_licensee = f.ReadInt32()
            if version_legacy < -2:
                for i in range(f.ReadInt32()):
                    custom_version_guid = f.ReadGuid()
                    custom_version = f.ReadInt32()
            
            section6_offset = f.ReadInt32()
            folder_name = f.ReadFString()
            package_flags = f.ReadUInt32()
            names_desc = ArrayDesc(f)
            if version_ue4 >= 459: gatherable_text_desc = ArrayDesc(f)
            exports_desc = ArrayDesc(f)
            imports_desc = ArrayDesc(f)
            depends_offset = f.ReadInt32()
            if version_ue4 >= 384: soft_pkg_refs_desc = ArrayDesc(f)
            if version_ue4 >= 510: searchable_names_desc_offset = f.ReadInt32()
            thumbnail_table_offset = f.ReadInt32()
            package_guid = f.ReadGuid()
            for i in range(f.ReadInt32()): gen_export_count, get_name_count = (f.ReadInt32(), f.ReadInt32())
            engine_version = EngineVersion.Read(f) if version_ue4 >= 336 else EngineVersion(4,0,0,f.ReadUInt32(),"")
            compatible_version = EngineVersion.Read(f) if version_ue4 >= 444 else engine_version
            compression_flags = f.ReadUInt32()
            compressed_chunks_count = f.ReadInt32()
            if compressed_chunks_count > 0: raise Exception("Asset has package-level compression and is likely too old to be parsed")
            package_source = f.ReadUInt32()
            for i in range(f.ReadInt32()): package = f.ReadFString()
            if version_legacy > -7:
                texture_alloc_count = f.ReadInt32()
                if texture_alloc_count > 0: raise Exception("Asset has texture allocation info and is likely too old to be parsed")
            asset_registry_data_offset = f.ReadInt32()
            bulk_data_offset = f.ReadInt64()
            world_tile_info_data_offset = f.ReadInt32() if version_ue4 >= 224 else 0
            if version_ue4 >= 326:
                for i in range(f.ReadInt32()): chunk_id = f.ReadInt32()
            elif version_ue4 >= 278: chunk_id = f.ReadInt32()
            if version_ue4 >= 507: preload_depends_desc = ArrayDesc(f)



            f.Seek(names_desc.offset)
            self.names = names = []
            for i in range(names_desc.count):
                name = f.ReadFString()
                names.append(name)
                if version_ue4 >= 504 and name != "": hash = f.ReadUInt32()
            
            self.imports = imports = []
            if imports_desc.offset > 0:
                f.Seek(imports_desc.offset)
                for i in range(imports_desc.count): imports.append(Import(f, names))
            
            self.exports = exports = []
            if exports_desc.offset > 0:
                f.Seek(exports_desc.offset)
                for i in range(exports_desc.count): exports.append(Export(f, self))
            
            dependencies = []
            if depends_offset > 0:
                f.Seek(depends_offset) # TODO: try seek
                for i in range(exports_desc.count):
                    data = []
                    for i_data in range(f.ReadInt32()): data.append(f.ReadInt32())
                    dependencies.append(data)

            soft_pkg_refs = []
            if soft_pkg_refs_desc.offset > 0:
                f.Seek(soft_pkg_refs_desc.offset)
                for i in range(soft_pkg_refs_desc.count): soft_pkg_refs.append(f.ReadFString())

            if asset_registry_data_offset > 0:
                f.Seek(asset_registry_data_offset)
                next_offset = world_tile_info_data_offset
                if separate_bulkdata_files and next_offset <= 0: next_offset = preload_depends_desc.offset
                if section6_offset > 0 and exports_desc.count > 0 and next_offset <= 0: next_offset = exports[0].serial_desc.offset
                if next_offset <= 0: next_offset = bulk_data_offset
                asset_registry_data = f.ReadBytes(next_offset - asset_registry_data_offset)
            else: asset_registry_data = None
            
            
            if world_tile_info_data_offset > 0:
                _3d = True # TODO: asset.GetCustomVersion<FFortniteMainBranchObjectVersion>()
                position = (f.ReadInt32(), f.ReadInt32(), f.ReadInt32() if _3d else 0)
                raise Exception("TODO: World Tile Info Data")
            else: world_tile_info = None

            if separate_bulkdata_files: raise Exception("TODO: Preload Dependencies")

            if section6_offset > 0 and exports_desc.count > 0:
                i_export_f = exports_desc.count - 1
                for i in range(exports_desc.count):
                    export = exports[i]
                    f.Seek(export.serial_desc.offset)

                    if i < i_export_f: next_offset = exports[i+1].serial_desc.offset
                    else:
                        p = f.Position()
                        f.Seek(-4, io.SEEK_END)
                        next_offset = f.Position()
                        f.Seek(p)

                    export_class = self.TryGetImport(export.class_index)
                    export_class_type = export_class.object_name.str if export_class else None

                    match export_class_type:
                        case "Function":
                            print(f"Skipping Export \"{export_class_type}\"")
                            continue
                        case _:
                            #if export_class_type.endswith("DataTable"): raise
                            #if export_class_type.endswith("StringTable"): raise
                            if export_class_type.endswith("BlueprintGeneratedClass"):
                                print(f"Skipping Export \"{export_class_type}\"")
                                continue
                            else: # Normal Export
                                while True:
                                    prop = UProperty() # TODO: self.TryReadProperty?
                                    if prop.TryRead(self): export.properties.append(prop)
                                    else: break

                            #match export_class_type: case "Enum" | "UserDefinedEnum": export.enum =
                    extras_len = next_offset - f.Position()
                    if extras_len < 0: raise
                    else: export.extras = f.ReadBytes(extras_len) if extras_len > 0 else None
            print("!")
class UProperty:
    def __repr__(self) -> str: return f"{self.name}({self.struct_type if hasattr(self,'struct_type') else self.type}) = {self.value}"
    def TryRead(self, asset:UAsset, header=True):
        f = asset.f
        self.name = f.ReadFName(asset.names).FullName()
        if self.name == "None": return None

        self.type = f.ReadFName(asset.names).str
        self.len = f.ReadInt32()
        self.i_dupe = f.ReadInt32()
        
        return self.TryReadData(asset, header)
    def TryReadData(self, asset:UAsset, header=True):
        if self.type == "None": raise
        f = asset.f
        
        match self.type:
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
                    case 0: raise
                    case _: raise
            case "Int8Property":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadInt8()
            case "Int16Property":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadInt16()
            case "IntProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadInt32()
            case "Int64Property":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadInt64()
            case "UInt16Property":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadUInt16()
            case "UInt32Property":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadUInt32()
            case "Int64Property":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadUInt64()
            case "FloatProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadFloat()
            case "DoubleProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadDouble()
            case "EnumProperty":
                if header:
                    self.enum_type = f.ReadFName(asset.names).str
                    self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadFName(asset.names).FullName()
            case "StrProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadFString()
            case "NameProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = f.ReadFName(asset.names).FullName()
            case "ObjectProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = asset.DecodePackageIndex(f.ReadInt32())
            case "MulticastDelegateProperty":
                if header: self.guid = asset.TryReadPropertyGuid()
                self.value = []
                for i in range(f.ReadInt32()): self.value.append((f.ReadInt32(), f.ReadFName(asset.names).FullName()))
            case "StructProperty":
                if header:
                    self.struct_type = f.ReadFName(asset.names).str
                    if asset.version_ue4 >= 441: self.struct_guid = f.ReadGuid()
                    self.guid = asset.TryReadPropertyGuid()

                header = False
                match self.struct_type:
                    #case "FloatRange": raise
                    case "Color":
                        if header: self.guid = asset.TryReadPropertyGuid()
                        bgra = f.ReadBytes(4)
                        self.value = (bgra[2],bgra[1],bgra[0],bgra[3]) # RGBA
                    case "LinearColor":
                        if header: self.guid = asset.TryReadPropertyGuid()
                        self.value = (f.ReadFloat(), f.ReadFloat(), f.ReadFloat(), f.ReadFloat()) # RGBA
                    case "Vector" | "Rotator":
                        if header: self.guid = asset.TryReadPropertyGuid()
                        self.value = (f.ReadFloat(), f.ReadFloat(), f.ReadFloat())
                    case "Guid":
                        self.value = f.ReadGuid()
                    case "ExpressionInput":
                        #p = f.Position()
                        self.value = FExpressionInput(asset)
                        #f.Seek(p)
                        #self.value = [x for x in f.ReadBytes(self.len)]
                    case "ColorMaterialInput" | "ScalarMaterialInput" | "VectorMaterialInput":
                        p = f.Position()
                        self.value = asset.GetExport(f.ReadInt32())
                        f.Seek(p + self.len)
                    #case "RichCurveKey" | "MovieSceneTrackIdentifier" | "MovieSceneFloatChannel": raise
                    case _:
                        self.value = [x for x in f.ReadBytes(self.len)]
                        print(f"Uknown Struct Type \"{self.struct_type}\"")
                        #raise Exception(f"Uknown Struct Type \"{struct_type}\"")
                
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
                            for i in range(element_count):
                                prop = UProperty()
                                prop.name, prop.type, prop.struct_type, prop.len = ("", self.array_el_type, self.array_el_full_type, element_size)
                                if prop.TryReadData(asset, False): self.value.append(prop)
                        except:
                            pass
                        finally:
                            f.Seek(next)
                else:
                    self.value = []
                    #size_1 = int(self.len / element_count)
                    #size_2 = int((self.len - 4) / element_count)
                    for i in range(element_count):
                        prop = UProperty()
                        prop.name, prop.type = ("", self.array_type)
                        if prop.TryReadData(asset, False): self.value.append(prop)
            case _: raise Exception(f"Uknown Property Type \"{self.type}\"")
        return True

UAsset(filepath)