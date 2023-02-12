from __future__ import annotations
from dataclasses import dataclass, fields
import bpy, io, uuid, time, math, os, sys, pathlib, subprocess
from struct import *
from ctypes import *
from mathutils import *
#from . import import_t3d

#dir = os.path.dirname(__file__)
#if dir not in sys.path: sys.path.append(dir)
#import import_t3d

#filepath = r"F:\Art\Assets\Game\Blender UE4 Importer\Samples\M_Base_Trim.uasset"
#filepath = r"F:\Art\Assets\Game\Blender UE4 Importer\Samples\Example_Stationary.umap"
#filepath = r"F:\Art\Assets\Game\Blender UE4 Importer\Samples\Example_Stationary_Test.umap"
#filepath = r"C:\Users\jdeacutis\Desktop\fSpy\New folder\Blender-UE4-Importer\Samples\M_Base_Trim.uasset"
filepath = r"C:\Users\jdeacutis\Desktop\fSpy\New folder\Blender-UE4-Importer\Samples\Example_Stationary.umap"
exported_base_dir = r"F:\Art\Assets"
project_dir = r"F:\Projects\Unreal Projects\Assets"
umodel_path = r"C:\Users\jdeacutis\Desktop\fSpy\New folder\Blender-UE4-Importer\umodel.exe"

logging = True
hide_noncasting = False

exported_base_dir = os.path.normpath(exported_base_dir)
project_dir = os.path.normpath(project_dir)
deg2rad = math.radians(1)

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

    def ReadStructure(self, ty : Structure): return ty.from_buffer_copy(self.byte_stream.read(sizeof(ty)))
    def ReadGuid(self): return uuid.UUID(bytes_le=self.ReadBytes(16))
    def ReadFString(self):
        length = self.ReadInt32()
        if length < 0: return self.ReadBytes(-2*length)[:-2].decode('utf-16')
        else: return self.ReadBytes(length)[:-1].decode('ascii')
    def ReadFName(self, names): return FName(self, names)
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
class FVector(PrintableStruct):
    _fields_ = ( ('x', c_float), ('y', c_float), ('z', c_float) )
    def __str__(self): return StructToString(self, False)
class FQuat(PrintableStruct):
    _fields_ = ( ('x', c_float), ('y', c_float), ('z', c_float), ('w', c_float) )
    def __str__(self): return StructToString(self, False)
class FColor(PrintableStruct): _fields_ = ( ('b', c_ubyte), ('g', c_ubyte), ('r', c_ubyte), ('a', c_ubyte) )
class FLinearColor(PrintableStruct): _fields_ = ( ('r', c_float), ('g', c_float), ('b', c_float), ('a', c_float) )
class FBox(PrintableStruct): _fields_ = ( ('min', FVector), ('max', FVector), ('valid', c_ubyte) )
class FBoxSphereBounds(PrintableStruct): _fields_ = ( ('origin', FVector), ('box_extent', FVector), ('sphere_radius', c_float) )
class FMeshSectionInfo(PrintableStruct): _fields_ = ( ('material_index', c_int), ('collision', c_bool), ('shadow', c_bool) )

prop_table_types = ( "ExpressionOutput", "StaticMaterial", "KAggregateGeom", "BodyInstance", "KConvexElem", "Transform", "StaticMeshSourceModel", "MeshBuildSettings", "MeshReductionSettings", 
                    "MeshUVChannelInfo", "AssetEditorOrbitCameraPosition" )

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
        if editor and asset.summary.version_ue4 >= 520: self.package_name = asset.f.ReadFName(asset.names)
        self.asset = asset
    @property
    def import_ref(self): return self.asset.TryGetImport(self.outer_index)
    def __repr__(self) -> str: return f"{self.object_name}({self.class_package}.{self.class_name})"
class Export: #FObjectExport
    def __init__(self, asset:UAsset):
        self.asset = asset
        f = asset.f
        self.class_index, self.super_index = (f.ReadInt32(), f.ReadInt32())
        if asset.summary.version_ue4 >= 508: self.template_index = f.ReadInt32()
        self.outer_index = f.ReadInt32()
        self.object_name = f.ReadFName(asset.names)
        self.object_flags = f.ReadUInt32()
        self.serial_desc = ArrayDesc(f, asset.summary.version_ue4 < 511)
        self.force_export, self.not_for_client, self.not_for_server = (f.ReadIntBool(), f.ReadIntBool(), f.ReadIntBool())
        self.package_guid = f.ReadGuid()
        self.package_flags = f.ReadUInt32()
        if asset.summary.version_ue4 >= 365: self.not_always_loaded_for_editor = f.ReadIntBool()
        if asset.summary.version_ue4 >= 465: self.is_asset = f.ReadIntBool()
        if asset.summary.version_ue4 >= 507:
            self.export_depends_offset = f.ReadInt32()
            self.ser_before_ser_depends_size = f.ReadInt32()
            self.create_before_ser_depends_size = f.ReadInt32()
            self.ser_before_create_depends_size = f.ReadInt32()
            self.create_before_create_depends_size = f.ReadInt32()
        
        self.properties = None
        self.export_class = asset.DecodePackageIndex(self.class_index)
        self.export_class_type = self.export_class.object_name.str if self.export_class else None
    def __repr__(self) -> str: return f"{self.object_name} [{len(self.properties) if self.properties != None else 'Unread'}]"
    def ReadProperties(self, read_children=True):
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
        self.extras = [x for x in self.asset.f.ReadBytes(extras_len)] if extras_len > 0 else None
        #match self.export_class_type:
            #case "ObjectProperty": # [0, i_exp(self), 1, 4, 4, 196, 0]
class Properties(dict):
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
        assert self.type != "None"
        f = asset.f
        
        match self.type:
            case "StructProperty":
                if header:
                    self.struct_type = f.ReadFName(asset.names).str
                    if asset.summary.version_ue4 >= 441: self.struct_guid = f.ReadGuid()
                    self.guid = asset.TryReadPropertyGuid()

                header = False
                p = f.Position()
                match self.struct_type:
                    case "Guid": self.value = f.ReadGuid()
                    case "Vector" | "Rotator": self.value = f.ReadStructure(FVector) #if header: self.guid = asset.TryReadPropertyGuid()
                    case "Quat": self.value = f.ReadStructure(FQuat)
                    case "Box": self.value = f.ReadStructure(FBox)
                    case "Color": self.value = f.ReadStructure(FColor)
                    case "LinearColor": self.value = f.ReadStructure(FLinearColor)
                    case "BoxSphereBounds": self.value = f.ReadStructure(FBoxSphereBounds)
                    case "ColorMaterialInput" | "ScalarMaterialInput" | "VectorMaterialInput":
                        p = f.Position()
                        self.value = asset.GetExport(f.ReadInt32())# TODO: other data is default value?
                        f.Seek(p + self.len)
                    case "ExpressionInput": self.value = FExpressionInput(asset)
                    case "StreamingTextureBuildInfo": self.value = [x for x in f.ReadBytes(self.len)]
                    #case "MeshSectionInfoMap":
                        #self.value = Properties().Read(asset)
                    case _:
                        if self.struct_type in prop_table_types:
                            self.value = Properties().Read(asset)
                        else:
                            self.value = [x for x in f.ReadBytes(self.len)]
                            if logging: print(f"Uknown Struct Type \"{self.struct_type}\"")
                            #raise Exception(f"Uknown Struct Type \"{struct_type}\"")
                p_diff = f.Position() - (p + self.len)
                if p_diff != 0:
                    f.Seek(p)
                    self.raw = [x for x in f.ReadBytes(self.len)]
                    if logging: print(f"Length Mismatch! {self.struct_type} : {p_diff}")
                
                assert self.len > 0
            case "ArrayProperty": # | "MapProperty":
                #if self.type == "MapProperty": f.ReadBytes(8)

                if header:
                    self.array_type = f.ReadFName(asset.names).str
                    self.guid = asset.TryReadPropertyGuid()
                element_count = f.ReadInt32()
                if self.array_type == "StructProperty":
                    if asset.summary.version_ue4 >= 500:
                        self.array_name = f.ReadFName(asset.names).FullName()
                        assert self.array_name != "None"
                        self.array_el_type = f.ReadFName(asset.names).str
                        assert self.array_el_type != "None"
                        assert self.array_type == self.array_el_type
                        self.array_size = f.ReadInt64()
                        self.array_el_full_type = f.ReadFName(asset.names).str
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
                    self.key_type = f.ReadFName(asset.names).str
                    self.value_type = f.ReadFName(asset.names).str
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
            for i in range(f.ReadInt32()):
                self.custom_version_guid = f.ReadGuid()
                self.custom_version = f.ReadInt32()
        
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
class UAsset:
    def __init__(self, filepath): self.filepath = filepath
    def __repr__(self) -> str: return f"\"{self.f.byte_stream.name}\", {len(self.imports)} Imports, {len(self.exports)} Exports"
    def GetImport(self, i) -> Import: return self.imports[-i - 1]
    def GetExport(self, i) -> Export: return self.exports[i - 1]
    def TryGetImport(self, i): return self.GetImport(i) if i < 0 else None
    def TryGetExport(self, i): return self.GetExport(i) if i > 0 else None
    def DecodePackageIndex(self, i):
        if i < 0: return self.GetImport(i)
        elif i > 0: return self.GetExport(i)
        else: return None #raise Exception("Invalid Package Index of 0")
    def TryReadPropertyGuid(self) -> uuid.UUID: return self.f.ReadGuid() if self.summary.version_ue4 >= 503 and self.f.ReadBool() else None
    #def TryReadProperty(self): # TODO
    def Read(self, read_all=True): # PackageReader.cpp
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
            for i in range(summary.exports_desc.count):
                self.exports[i].ReadProperties(not read_all)
            self.f.byte_stream.close()
            print(f"Imported {self} in {time.time() - t0:.2f}s")
    def Close(self): self.f.byte_stream.close()
    def __enter__(self):
        self.Read(False)
        return self
    def __exit__(self, *args): self.Close()

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

def ArchiveToProjectPath(path): return os.path.join(project_dir, "Content", str(pathlib.Path(path).relative_to("\\Game"))) + ".uasset"
def SetupObject(context, name, data=None):
    obj = bpy.data.objects.new(name, data)
    obj.rotation_mode = 'YXZ'
    context.collection.objects.link(obj)
    return obj
def Transform(export:Export, obj, pitch_offset=0):
    props = export.properties

    # Unreal: X+ Forward, Y+ Right, Z+ Up     Blender: X+ Right, Y+ Forward, Z+ Up
    rel_loc = props.TryGetValue('RelativeLocation')
    if rel_loc: obj.location = Vector((rel_loc[1],rel_loc[0],rel_loc[2])) * 0.01
    
    # Unreal: Roll, Pitch, Yaw     File: Pitch, Yaw, Roll     Blender: Pitch, Roll, -Yaw     0,0,0 = fwd, down for lights
    rel_rot = props.TryGetValue('RelativeRotation')
    if rel_rot: obj.rotation_euler = Euler(((rel_rot[0]+pitch_offset)*deg2rad, rel_rot[2]*deg2rad, -rel_rot[1]*deg2rad))

    rel_scale = props.TryGetValue('RelativeScale3D')
    if rel_scale: obj.scale = Vector((rel_scale[1],rel_scale[0],rel_scale[2]))
def TryApplyRootComponent(export:Export, obj, pitch_offset=0):
    root_exp = export.properties.TryGetValue('RootComponent')
    if root_exp:
        Transform(root_exp, obj, pitch_offset)
        return True
    return False
def TryGetExtractedImport(imp:Import, extract_dir):
    archive_path = imp.object_name.str
    extracted_imports = {}
    extracted = extracted_imports.get(archive_path)
    if not extracted:
        asset_path = ArchiveToProjectPath(archive_path)
        extracted_path = extract_dir+archive_path
        match type:
            case 'StaticMesh':
                subprocess.run(f"\"{umodel_path}\" -export -gltf -out=\"{extract_dir}\" \"{asset_path}\"")
                #bpy.ops.import_scene.gltf(filepath=extracted_path, merge_vertices=True, import_pack_images=False)
            case 'Texture':
                subprocess.run(f"\"{umodel_path}\" -export -png -out=\"{extract_dir}\" \"{asset_path}\"")
                #bpy.data.images.load(extracted_path, check_existing=True)
            case _: raise
        raise
        extracted_imports[archive_path] = extracted
    return extracted
def TryGetStaticMesh(static_mesh_comp:Export):
    mesh = None
    static_mesh = static_mesh_comp.properties.TryGetValue('StaticMesh')
    if static_mesh:
        mesh_name = static_mesh.object_name.str
        mesh = bpy.data.meshes.get(mesh_name)
        if not mesh:
            mesh_import = static_mesh.import_ref
            if mesh_import:
                mesh_path = os.path.normpath(f"{exported_base_dir}{mesh_import.object_name.str}.FBX")
                return mesh
                mesh = ImportUnrealFbx(mesh_path)[0].data
                mesh.name = mesh_name
                mesh.transform(Euler((0,0,90*deg2rad)).to_matrix().to_4x4()*0.01)
    return mesh
def ProcessSceneExport(export:Export):
    match export.export_class_type:
        case 'PointLight' | 'SpotLight':
            export.ReadProperties()

            match export.export_class_type:
                case 'PointLight': light_type = 'POINT'
                case 'SpotLight': light_type = 'SPOT'
                case _: raise # TODO: Sun Light

            light = bpy.data.lights.new(export.object_name.str, light_type)
            light_obj = SetupObject(bpy.context, light.name, light)
            TryApplyRootComponent(export, light_obj, -90) # Blender lights are cursed, local Z- Forward, Y+ Up, X+ Right
            
            light_comp = export.properties.TryGetValue('LightComponent')
            if light_comp:
                light_props = light_comp.properties
                light.energy = light_props.TryGetValue('Intensity')
                color = light_props.TryGetValue('LightColor')
                if color: light.color = Color(color[:3]) / 255.0
                cast = light_props.TryGetValue('CastShadows')
                if cast != None:
                    light.use_shadow = cast
                    if not cast and hide_noncasting: light_obj.hide_viewport = light_obj.hide_render = True
                light.shadow_soft_size = light_props.TryGetValue('SourceRadius', 0.05)

                if light_type == 'SPOT':
                    outer_angle = light_props.TryGetValue('OuterConeAngle')
                    inner_angle = light_props.TryGetValue('InnerConeAngle', 0)
                    light.spot_size = outer_angle * deg2rad
                    light.spot_blend = 1 - (inner_angle / outer_angle)
        case 'StaticMeshActor':
            export.ReadProperties()

            static_mesh_comp = export.properties.TryGetValue('StaticMeshComponent')
            if static_mesh_comp: mesh = TryGetStaticMesh(static_mesh_comp)
            
            obj = SetupObject(bpy.context, export.object_name.str, mesh)
            TryApplyRootComponent(export, obj)
        case _:
            if export.export_class.class_name == 'BlueprintGeneratedClass':
                export.ReadProperties()

                bp_obj = SetupObject(bpy.context, export.object_name.str)
                TryApplyRootComponent(export, bp_obj)
                root_comp = export.properties.TryGetValue('RootComponent')
                root_comp.bl_obj = bp_obj

                bp_comps = export.properties.TryGetValue('BlueprintCreatedComponents')
                if bp_comps:
                    if not hasattr(export.asset, 'import_cache'): export.asset.import_cache = {}

                    bp_path = export.export_class.import_ref.object_name.str
                    bp_asset = export.asset.import_cache.get(bp_path)
                    if not bp_asset:
                        export.asset.import_cache[bp_path] = bp_asset = UAsset(ArchiveToProjectPath(bp_path))
                        bp_asset.Read(False)
                        bp_asset.name2exp = {}
                        for exp in bp_asset.exports: bp_asset.name2exp[exp.object_name.str] = exp
                    
                    for comp in bp_comps:
                        child_export = comp.value
                        #ProcessSceneExport(child_export) # TODO? Can't, need to partly process gend_exp & child_export
                        if child_export.export_class_type == 'StaticMeshComponent':
                            gend_exp = bp_asset.name2exp.get(f"{child_export.object_name.str}_GEN_VARIABLE")
                            if gend_exp:
                                gend_exp.ReadProperties()

                                mesh = TryGetStaticMesh(gend_exp)
                                child_export.bl_obj = obj = SetupObject(bpy.context, child_export.object_name.str, mesh)

                                attach = child_export.properties.TryGetValue('AttachParent') # TODO: unify?
                                if attach:
                                    assert hasattr(attach, 'bl_obj')
                                    obj.parent = attach.bl_obj

                                Transform(gend_exp, obj)
                return
def LoadUAssetScene(filepath):
    with UAsset(filepath) as asset:
        for export in asset.exports:
            ProcessSceneExport(export)
        if hasattr(asset, 'import_cache'):
            for imp_asset in asset.import_cache.values(): imp_asset.Close()

#asset = UAsset(r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Materials\M_Base_Trim.uasset")
#asset = UAsset(r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Maps\Example_Stationary.umap")
asset = UAsset(r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Meshes\SM_Door_Small_A.uasset")
asset.Read(False)
#LoadUAssetScene(filepath)

sm = asset.exports[5]
sm.ReadProperties()
bnds = sm.properties['ExtendedBounds']

#asset_path = r"C:\Users\jdeacutis\Desktop\fSpy\New folder\Blender-UE4-Importer\Samples\T_Lights_Diff.uasset"
#subprocess.run((umodel_path, "-export", "-png", asset_path))
#subprocess.run(f"\"{umodel_path}\" -export -png \"{asset_path}\"")

print("Done")