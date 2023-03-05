import os, io, sys, math, uuid, bpy, bmesh, importlib
from ctypes import *

cur_dir = os.path.dirname(__file__)
if cur_dir not in sys.path: sys.path.append(cur_dir)
import import_uasset, import_umat
from import_uasset import UAsset, Export, FStripDataFlags, FVector, FVector2D, FColor, Euler, ArchiveToProjectPath
from import_umat import ImportUMaterial

def ImportStaticMesh(self:Export, import_materials=True):
    self.ReadProperties(False, False)

    asset = self.asset
    f = self.asset.f
    
    if f.ReadInt32(): self.guid = f.ReadGuid()
    
    strip_flags = f.ReadStructure(FStripDataFlags) if asset.summary.version_ue4 >= 130 else FStripDataFlags()
    cooked = f.ReadBool32()
    body_setup = asset.DecodePackageIndex(f.ReadInt32())
    if asset.summary.version_ue4 >= 216: nav_collision = asset.DecodePackageIndex(f.ReadInt32())
    
    editor_data_stripped = (strip_flags.global_strip_flags & 1) != 0
    if not editor_data_stripped:
        assert asset.summary.version_ue4 >= 242
        highres_source_mesh_name = f.ReadFString()
        highres_source_mesh_crc = f.ReadUInt32()

    lighting_guid = f.ReadGuid()

    # TArray<UStaticMeshSocket*> Sockets
    count = f.ReadInt32()
    assert count == 0

    obj_guid = uuid.UUID('E4B068ED-42E9-F494-0BDA-31A241BB462E')
    obj_version = asset.summary.custom_versions[obj_guid]
    editor = not (asset.summary.package_flags & 0x8)

    if not editor_data_stripped:
        for src_model in self.properties['SourceModels'].value:
            assert obj_version < 28 # FEditorObjectVersion::StaticMeshDeprecatedRawMesh
            # FByteBulkData
            flags = f.ReadUInt32()
            assert not (flags & 0x2) # BULKDATA_Size64Bit
            count = f.ReadUInt32()
            byte_size = f.ReadUInt32()
            offset = f.ReadInt32() if asset.summary.version_ue4 < 198 else f.ReadInt64()
            if not (flags & 0x1): offset += asset.summary.bulk_data_offset # BULKDATA_NoOffsetFixUp

            assert not (flags & 0x20 or count == 0)
            assert not (flags & (0x800|0x100))
            if flags & 0x1:
                p = f.Position()

                # FByteBulkData::SerializeData
                assert asset.summary.compression_flags == 0
                f.Seek(asset.summary.bulk_data_offset + offset)
                
                # FRawMesh
                version, version_licensee = (f.ReadInt32(), f.ReadInt32())
                face_mat_indices = f.ReadStructure(c_int32 * f.ReadInt32())
                f.Seek(sizeof(c_uint32) * f.ReadInt32(), io.SEEK_CUR)#face_smoothing_mask = asset.f.ReadStructure(c_uint32 * asset.f.ReadInt32())
                vertices = f.ReadStructure(FVector * f.ReadInt32())
                wedge_indices = f.ReadStructure(c_int32 * f.ReadInt32())
                f.Seek(sizeof(FVector) * f.ReadInt32(), io.SEEK_CUR)#wedge_tangents = asset.f.ReadStructure(FVector * asset.f.ReadInt32())
                f.Seek(sizeof(FVector) * f.ReadInt32(), io.SEEK_CUR)#wedge_binormals = asset.f.ReadStructure(FVector * asset.f.ReadInt32())
                wedge_normals = f.ReadStructure(FVector * f.ReadInt32())
                wedge_uvs = []
                for i_uv in range(8): wedge_uvs.append(f.ReadStructure(FVector2D * f.ReadInt32()))
                wedge_colors = f.ReadStructure(FColor * f.ReadInt32())
                if version >= 1: mat_index_to_import_index = f.ReadStructure(c_int32 * f.ReadInt32())

                mdl_bm = bmesh.new()
                for pos in vertices: mdl_bm.verts.new(pos.ToVector())
                mdl_bm.verts.ensure_lookup_table()
                
                uvs = []
                for i_uv in range(len(wedge_uvs)):
                    if len(wedge_uvs[i_uv]) > 0: uvs.append(mdl_bm.loops.layers.uv.new(f"UV{i_uv}"))
                
                if len(wedge_colors) > 0:
                    mdl_bm.loops.layers.color.new("Color") # data.color_attributes?
                    assert False

                spl_norms = []
                for i_wedge in range(2, len(wedge_indices), 3):
                    face = mdl_bm.faces.new((
                        mdl_bm.verts[wedge_indices[i_wedge]],
                        mdl_bm.verts[wedge_indices[i_wedge-1]],
                        mdl_bm.verts[wedge_indices[i_wedge-2]]
                    ))
                    face.material_index = face_mat_indices[int(i_wedge / 3)]
                    for i_loop in range(3): spl_norms.append(wedge_normals[i_wedge - i_loop].ToVector())
                    for i_uv in range(len(uvs)):
                        uv_lay = uvs[i_uv]
                        w_uvs = wedge_uvs[i_uv]
                        for i_loop in range(3):
                            uv = w_uvs[i_wedge - i_loop]
                            face.loops[i_loop][uv_lay].uv = (uv.x, -uv.y)
                
                mesh = bpy.data.meshes.new(self.object_name.str)
                mdl_bm.to_mesh(mesh)
                mesh.normals_split_custom_set(spl_norms)
                mesh.use_auto_smooth = True
                mesh.transform(Euler((0,0,math.radians(90))).to_matrix().to_4x4()*0.01)
                mesh["UAsset"] = self.asset.f.byte_stream.name
                # TODO: flip_normals() faster?

                f.Seek(p)
            guid, is_hash = (f.ReadGuid(), f.ReadBool32())

    assert not cooked
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
            
            if import_materials:
                umat_imp = mat_interface.import_ref.object_name.str
                umat_path = ArchiveToProjectPath(umat_imp)
                mat, graph_data = ImportUMaterial(umat_path, mat_mesh=mesh)
                mesh.materials.append(mat)
    
    # remaining is SpeedTree
    return mesh
def ImportStaticMeshUAsset(filepath:str, import_materials=True):
    asset = UAsset(filepath)
    asset.Read(False)
    for export in asset.exports:
        match export.export_class_type:
            case 'StaticMesh': return ImportStaticMesh(export, import_materials)
    return None

if __name__ != "import_umesh":
    importlib.reload(import_uasset)
    importlib.reload(import_umat)

    ImportStaticMeshUAsset(cur_dir + r"\Samples\SM_Door_Small_A.uasset")

    print("Done")