import os, io, sys, math, uuid, bpy, bmesh, importlib, time
from ctypes import *
from mathutils import Vector

cur_dir = os.path.dirname(__file__)
if cur_dir not in sys.path: sys.path.append(cur_dir)
import import_uasset, import_umat
from import_uasset import UAsset, Export, FStripDataFlags, FVector, FVector2D, FColor, Euler
from import_umat import TryGetUMaterialImport

def ReadMeshBulkData(self:Export, asset:UAsset, f:import_uasset.ByteStream): # FByteBulkData
    flags = f.ReadUInt32()
    assert not (flags & 0x2) # BULKDATA_Size64Bit
    count = f.ReadUInt32()
    byte_size = f.ReadUInt32()
    offset = f.ReadInt32() if asset.summary.version_ue4 < 198 else f.ReadInt64()
    if not (flags & 0x10000): offset += asset.summary.bulk_data_offset # BULKDATA_NoOffsetFixUp

    if flags & 0x20 or count == 0: return None # No data
    assert not (flags & (0x800|0x100)) # OptionalPayload|PayloadInSeperateFile
    if flags & 0x1: # PayloadAtEndOfFile
        p = f.Position()

        # FByteBulkData::SerializeData
        assert asset.summary.compression_flags == 0
        f.Seek(offset)
        
        # FRawMesh
        version, version_licensee = (f.ReadInt32(), f.ReadInt32())
        face_mat_indices:list[c_int32] = f.ReadStructure(c_int32 * f.ReadInt32())
        f.Seek(sizeof(c_uint32) * f.ReadInt32(), io.SEEK_CUR)#face_smoothing_mask = asset.f.ReadStructure(c_uint32 * asset.f.ReadInt32())
        vertices:list[FVector] = f.ReadStructure(FVector * f.ReadInt32())
        wedge_indices = f.ReadStructure(c_int32 * f.ReadInt32())
        f.Seek(sizeof(FVector) * f.ReadInt32(), io.SEEK_CUR)#wedge_tangents = asset.f.ReadStructure(FVector * asset.f.ReadInt32())
        f.Seek(sizeof(FVector) * f.ReadInt32(), io.SEEK_CUR)#wedge_binormals = asset.f.ReadStructure(FVector * asset.f.ReadInt32())
        wedge_normals:list[FVector] = f.ReadStructure(FVector * f.ReadInt32())
        wedge_uvs:list[list[FVector2D]] = []
        for i_uv in range(8): wedge_uvs.append(f.ReadStructure(FVector2D * f.ReadInt32()))
        wedge_colors:list[FColor] = f.ReadStructure(FColor * f.ReadInt32())
        if version >= 1: mat_index_to_import_index = f.ReadStructure(c_int32 * f.ReadInt32())

        mdl_bm = bmesh.new()
        for pos in vertices: mdl_bm.verts.new(Vector((pos.y, pos.x, pos.z)))
        mdl_bm.verts.ensure_lookup_table()
        
        uvs = []
        for i_uv in range(len(wedge_uvs)):
            if len(wedge_uvs[i_uv]) > 0: uvs.append(mdl_bm.loops.layers.uv.new(f"UV{i_uv}"))
        
        if len(wedge_colors) > 0:
            col_lay = mdl_bm.loops.layers.color.new("Color") # data.color_attributes?

        spl_norms = []
        for i_wedge in range(0, len(wedge_indices), 3):
            try:
                face = mdl_bm.faces.new((
                    mdl_bm.verts[wedge_indices[i_wedge]],
                    mdl_bm.verts[wedge_indices[i_wedge+1]],
                    mdl_bm.verts[wedge_indices[i_wedge+2]]
                ))
                loops = face.loops
                i_poly = int(i_wedge / 3)
                #face.smooth = face_smoothing_mask[i_poly] == 0
                face.material_index = face_mat_indices[i_poly]

                #n = wedge_normals[i_wedge]
                #spl_norms.append(Vector((n.y, n.x, n.z)))

                for i_uv in range(len(uvs)):
                    uv_lay = uvs[i_uv]
                    w_uvs = wedge_uvs[i_uv]
                    
                    uv1 = w_uvs[i_wedge + 0]
                    uv2 = w_uvs[i_wedge + 1]
                    uv3 = w_uvs[i_wedge + 2]
                    loops[0][uv_lay].uv = (uv1.x, 1-uv1.y)
                    loops[1][uv_lay].uv = (uv2.x, 1-uv2.y)
                    loops[2][uv_lay].uv = (uv3.x, 1-uv3.y)
                if len(wedge_colors) > 0:
                    col1 = wedge_colors[i_wedge + 0]
                    col2 = wedge_colors[i_wedge + 1]
                    col3 = wedge_colors[i_wedge + 2]
                    loops[0][col_lay] = Vector((col1.r,col1.g,col1.b,col1.a)) / 255.0
                    loops[1][col_lay] = Vector((col2.r,col2.g,col2.b,col2.a)) / 255.0
                    loops[2][col_lay] = Vector((col3.r,col3.g,col3.b,col3.a)) / 255.0
            except ValueError: pass # Face already exists
        
        for i_wn in range(0, len(wedge_indices)):
            n = wedge_normals[i_wn]
            spl_norms.append(Vector((n.y, n.x, n.z)))

        mesh = bpy.data.meshes.new(self.object_name)
        mdl_bm.to_mesh(mesh)
        mesh.normals_split_custom_set(spl_norms)
        mesh.use_auto_smooth = True
        mesh.transform(Euler((0,0,math.radians(0))).to_matrix().to_4x4()*0.01)
        mesh["UAsset"] = self.asset.f.byte_stream.name
        # TODO: flip_normals() faster?

        f.Seek(p)
        return mesh
def ImportStaticMesh(self:Export, import_materials=True, log=True):
    t0 = time.time()
    asset = self.asset
    f = self.asset.f
    
    self.ReadProperties(False, False)
    if f.ReadInt32(): self.guid = f.ReadGuid()
    
    strip_flags = f.ReadStructure(FStripDataFlags) if asset.summary.version_ue4 >= 130 else FStripDataFlags()
    cooked = f.ReadBool32()
    body_setup = asset.DecodePackageIndex(f.ReadInt32())
    if asset.summary.version_ue4 >= 216: nav_collision = asset.DecodePackageIndex(f.ReadInt32())
    
    editor_data_stripped = (strip_flags.global_strip_flags & 1) != 0
    if not editor_data_stripped:
        assert asset.summary.version_ue4 >= 242
        highres_source_mesh_name, crc = (f.ReadFString(), f.ReadUInt32())

    lighting_guid = f.ReadGuid()

    socket_count = f.ReadInt32()# TArray<UStaticMeshSocket*> Sockets
    assert socket_count == 0

    obj_guid = uuid.UUID('E4B068ED-42E9-F494-0BDA-31A241BB462E')
    obj_version = asset.summary.custom_versions[obj_guid]
    editor = not (asset.summary.package_flags & 0x8)

    if not editor_data_stripped:
        for src_model in self.properties['SourceModels'].value:
            assert obj_version < 28 # FEditorObjectVersion::StaticMeshDeprecatedRawMesh
            lod_mesh = ReadMeshBulkData(self, asset, f)
            if lod_mesh: mesh = lod_mesh
            guid, is_hash = (f.ReadGuid(), f.ReadBool32())

    assert not cooked

    ue4_14_or_above = True # TODO
    if ue4_14_or_above:
        speedtree_wind = f.ReadBool32()
        assert not speedtree_wind

        if obj_version >= 8:
            # TArray<FStaticMaterial> StaticMaterials
            count = f.ReadInt32()
            for i in range(count):
                mat_interface, mat_slot_name = (asset.DecodePackageIndex(f.ReadInt32()), f.ReadFName(asset.names))
                if editor: imported_mat_slot_name = f.ReadFName(asset.names)
                if obj_version >= 10:
                    initialized, override_densities = (f.ReadBool32(), f.ReadBool32())
                    local_uv_densities = (f.ReadFloat(), f.ReadFloat(), f.ReadFloat(), f.ReadFloat())
                
                if import_materials: mesh.materials.append(TryGetUMaterialImport(mat_interface, mat_mesh=mesh))
        
        # remaining is SpeedTree

    if log: print(f"Imported {self.object_name} ({len(mesh.vertices)} Verts, {len(mesh.polygons)} Tris, {len(mesh.materials)} Materials): {(time.time() - t0) * 1000:.2f}ms")
    return mesh
def ImportStaticMeshUAsset(filepath:str, import_materials=True, log=False):
    asset = UAsset(filepath)
    asset.Read(False)
    for export in asset.exports:
        match export.export_class_type:
            case 'StaticMesh': return ImportStaticMesh(export, import_materials, log)
    if log: print(f"\"{filepath}\" Static Mesh Export Not Found")
    return None

if __name__ != "import_umesh":
    importlib.reload(import_uasset)
    importlib.reload(import_umat)

    #filepath = r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Meshes\SM_Door_Small_A.uasset"
    filepath = r"F:\Projects\Unreal Projects\Assets\Content\VehicleVarietyPack\Meshes\SM_Truck_Box.uasset"
    #filepath = r"F:\Projects\Unreal Projects\Assets\Content\VehicleVarietyPack\Meshes\SM_Hatchback.uasset"
    #filepath = r"F:\Projects\Unreal Projects\Assets\Content\VehicleVarietyPack\Meshes\SM_Pickup.uasset"
    #filepath = r"F:\Projects\Unreal Projects\Assets\Content\VehicleVarietyPack\Meshes\SM_SportsCar.uasset"

    mesh = ImportStaticMeshUAsset(filepath, False, True)
    bpy.context.collection.objects.link(bpy.data.objects.new(mesh.name, mesh))

    print("Done")