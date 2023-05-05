import os, io, sys, math, uuid, bpy, bmesh, importlib, time, struct
from ctypes import *
from mathutils import Vector, Matrix
from bpy.props import *
from bpy_extras.io_utils import ImportHelper

cur_dir = os.path.dirname(__file__)
if cur_dir not in sys.path: sys.path.append(cur_dir)
import uasset, umat, register_helper
from uasset import UAsset, Export, FStripDataFlags, FVector, FVector4, FVector2D, FColor, Euler, PrintableStruct
from umat import TryGetUMaterialImport

def uint16_to_float(value:c_uint16):
    sign = (value >> 15) & 0b0000000000000001
    exp  = (value >> 10) & 0b0000000000011111
    mant =  value        & 0b0000001111111111
    exp  = exp + (127 - 15)
    return struct.unpack('<f', struct.pack('<I', (sign << 31) | (exp << 23) | (mant << 13)))[0]

class FApexClothPhysToRenderVertData(PrintableStruct): _fields_ = ( ('pos_bary_d', FVector4), ('normal_bary_d', FVector4), ('tang_bary_d', FVector4), ('simul_mesh_vert_inds', c_int16 * 4), ('pad', c_int32 * 2) )
class FPackedNormal(PrintableStruct):
    _fields_ = ( ('packed', c_uint32), )
    def Unpack(self):
        # TODO: Handle 4.20: ^ 0b10000000100000001000000010000000 # offset by 128
        return ( # Y, X, Z
            ((self.packed >> 8 ) & 0xFF) / 127.5 - 1,
            ( self.packed        & 0xFF) / 127.5 - 1,
            ((self.packed >> 16) & 0xFF) / 127.5 - 1
        )
class FMeshUVHalf(PrintableStruct):
    _fields_ = ( ('u', c_uint16), ('v', c_uint16) )
    def ToFloat2(self): return (uint16_to_float(self.u), 1 - uint16_to_float(self.v))
class BulkHeader:
    def Read(self, f:uasset.ByteStream, summary:uasset.USummary):
        self.flags = f.ReadUInt32()
        b64 = self.flags & 0x2000 # Size64Bit
        assert not b64
        self.count = f.ReadUInt64() if b64 else f.ReadUInt32()
        self.byte_size = f.ReadUInt64() if b64 else f.ReadUInt32()
        self.offset = f.ReadInt32() if summary.version_ue4 < 198 else f.ReadInt64()
        if not (self.flags & 0x10000): self.offset += summary.bulk_data_offset # NoOffsetFixUp
        return self

v_obj_guid = uuid.UUID('E4B068ED-42E9-F494-0BDA-31A241BB462E') # 0xE4B068ED, 0xF49442E9, 0xA231DA0B, 0x2E46BB41
v_ent_obj_guid = uuid.UUID('9DFFBCD6-0158-494F-8212-21E288A8923C') # 0x9DFFBCD6, 0x494F0158, 0xE2211282, 0x3C92A888
v_tang_guid = uuid.UUID('5579F886-4C1F-933A-7B08-BA832FB96163') # 
v_ren_guid = uuid.UUID('12F88B9F-4AFC-8875-0CD9-7CA629BD3A38') # 0x12F88B9F, 0x88754AFC, 0xA67CD90C, 0x383ABD29
v_skel_guid = uuid.UUID('D78A4A00-4697-E858-B519-A8BAB4467D48') # 0xD78A4A00, 0xE8584697, 0xBAA819B5, 0x487D46B4

def ReadStripFlags(f:uasset.ByteStream, summary:uasset.USummary, min_v = 130) -> FStripDataFlags: return f.ReadStructure(FStripDataFlags) if summary.version_ue4 >= min_v else FStripDataFlags()
def ReadFMultisizeIndexContainer(f:uasset.ByteStream, summary:uasset.USummary):
    if summary.version_ue4 < 283: need_cpu_access = f.ReadBool32() # VER_UE4_KEEP_SKEL_MESH_INDEX_DATA
    size = f.ReadUInt8()
    return f.ReadBulkArray(c_uint16 if size == 2 else c_uint32)
def ReadMeshBulkData(self:Export, asset:UAsset, f:uasset.ByteStream): # FByteBulkData
    bulk = BulkHeader().Read(f, asset.summary)

    if bulk.flags & 0x20 or bulk.count == 0: return None # BULKDATA_Unused, No data
    assert not (bulk.flags & (0x100 | 0x800)) # PayloadInSeperateFile | OptionalPayload
    if bulk.flags & 0x1: # PayloadAtEndOfFile
        assert bulk.offset + 16 <= os.fstat(f.byte_stream.raw.fileno()).st_size, "Offset is outside file"
        p = f.Position()

        # FByteBulkData::SerializeData
        assert asset.summary.compression_flags == 0
        f.Seek(bulk.offset)

        if bulk.flags & (0x02 | 0x10 | 0x80): raise # CompressedZlib | CompressedLzo | CompressedLzx
        
        # FRawMesh
        version, version_licensee = (f.ReadInt32(), f.ReadInt32())
        face_mat_indices:list[c_int32] = f.ReadArray(c_int32)
        f.SkipArray(c_uint32)#face_smoothing_mask = f.ReadArray(c_uint32)
        vertices:list[FVector] = f.ReadArray(FVector)
        wedge_indices = f.ReadArray(c_int32)
        f.SkipArray(FVector)#wedge_tangents = f.ReadArray(FVector)
        f.SkipArray(FVector)#wedge_binormals = f.ReadArray(FVector)
        wedge_normals:list[FVector] = f.ReadArray(FVector)
        wedge_uvs:list[list[FVector2D]] = []
        for i_uv in range(8): wedge_uvs.append(f.ReadArray(FVector2D))
        wedge_colors:list[FColor] = f.ReadArray(FColor)
        if version >= 1: mat_index_to_import_index = f.ReadArray(c_int32)

        bmsh = bmesh.new()
        for pos in vertices: bmsh.verts.new(Vector((pos.y, pos.x, pos.z)))
        bmsh.verts.ensure_lookup_table()
        
        uvs = []
        for i_uv in range(len(wedge_uvs)):
            if len(wedge_uvs[i_uv]) > 0: uvs.append(bmsh.loops.layers.uv.new(f"UV{i_uv}"))
        
        if len(wedge_colors) > 0:
            col_lay = bmsh.loops.layers.color.new("Color")

        spl_norms = []
        for i_wedge in range(0, len(wedge_indices), 3):
            try:
                face = bmsh.faces.new((
                    bmsh.verts[wedge_indices[i_wedge+0]],
                    bmsh.verts[wedge_indices[i_wedge+1]],
                    bmsh.verts[wedge_indices[i_wedge+2]]
                ))
                loops = face.loops
                i_poly = int(i_wedge / 3)
                #face.smooth = face_smoothing_mask[i_poly] == 0
                face.material_index = face_mat_indices[i_poly]

                n1 = wedge_normals[i_wedge + 0]
                n2 = wedge_normals[i_wedge + 1]
                n3 = wedge_normals[i_wedge + 2]
                spl_norms.append(Vector((n1.y, n1.x, n1.z)))
                spl_norms.append(Vector((n2.y, n2.x, n2.z)))
                spl_norms.append(Vector((n3.y, n3.x, n3.z)))

                for i_uv in range(len(uvs)):
                    uv1 = wedge_uvs[i_uv][i_wedge + 0]
                    uv2 = wedge_uvs[i_uv][i_wedge + 1]
                    uv3 = wedge_uvs[i_uv][i_wedge + 2]
                    loops[0][uvs[i_uv]].uv = (uv1.x, 1-uv1.y)
                    loops[1][uvs[i_uv]].uv = (uv2.x, 1-uv2.y)
                    loops[2][uvs[i_uv]].uv = (uv3.x, 1-uv3.y)
                if len(wedge_colors) > 0:
                    col1 = wedge_colors[i_wedge + 0]
                    col2 = wedge_colors[i_wedge + 1]
                    col3 = wedge_colors[i_wedge + 2]
                    loops[0][col_lay] = Vector((col1.r,col1.g,col1.b,col1.a)) / 255.0
                    loops[1][col_lay] = Vector((col2.r,col2.g,col2.b,col2.a)) / 255.0
                    loops[2][col_lay] = Vector((col3.r,col3.g,col3.b,col3.a)) / 255.0
            except ValueError: pass # Face already exists

        mesh = bpy.data.meshes.new(self.object_name)
        mesh.name = self.object_name
        bmsh.to_mesh(mesh)
        mesh.normals_split_custom_set(spl_norms)
        mesh.use_auto_smooth = True
        mesh.transform(Matrix.Identity(4) * 0.01)
        mesh["UAsset"] = self.asset.f.byte_stream.name
        # TODO: flip_normals() faster?

        f.Seek(p)
        return mesh
def ReadFSkelMeshVertexBase(f:uasset.ByteStream, v_ren):
    pos = f.ReadStructure(FVector)
    if v_ren < 26: packed_normals = f.ReadStructure(FPackedNormal * 3) # IncreaseNormalPrecision
    else: new_nx, new_ny, new_nz = (f.ReadStructure(FVector), f.ReadStructure(FVector), f.ReadStructure(FVector4))
def ImportStaticMesh(self:Export, import_materials=True, log=True):
    t0 = time.time()
    asset = self.asset
    f = self.asset.f
    
    self.ReadProperties(False, False)
    if f.ReadInt32(): self.guid = f.ReadGuid()
    
    strip_flags = ReadStripFlags(f, asset.summary)
    cooked = f.ReadBool32()
    body_setup = asset.DecodePackageIndex(f.ReadInt32())
    if asset.summary.version_ue4 >= 216: nav_collision = asset.DecodePackageIndex(f.ReadInt32())
    
    editor_data_stripped = strip_flags.StripForEditor()
    if not editor_data_stripped:
        assert asset.summary.version_ue4 >= 242
        highres_source_mesh_name, crc = (f.ReadFString(), f.ReadUInt32())

    lighting_guid = f.ReadGuid()

    socket_count = f.ReadInt32()# TArray<UStaticMeshSocket*> Sockets
    assert socket_count == 0

    v_obj = asset.summary.custom_versions.get(v_obj_guid, 0)
    editor = not (asset.summary.package_flags & 0x8)

    if not editor_data_stripped:
        for src_model in self.properties['SourceModels'].value:
            if v_obj < 28: # FEditorObjectVersion::StaticMeshDeprecatedRawMesh
                lod_mesh = ReadMeshBulkData(self, asset, f)
                if lod_mesh: mesh = lod_mesh
                guid, is_hash = (f.ReadGuid(), f.ReadBool32())
            elif f.ReadBool32():
                lod_mesh = ReadMeshBulkData(self, asset, f)
                if lod_mesh: mesh = lod_mesh

                if v_obj >= 29: guid = f.ReadGuid() # FEditorObjectVersion::MeshDescriptionBulkDataGuid
                v_enterprise_obj = asset.summary.custom_versions.get(v_ent_obj_guid, 0)
                if v_enterprise_obj >= 8: is_hash = f.ReadBool32() # FEnterpriseObjectVersion::MeshDescriptionBulkDataGuidIsHash

    assert not cooked

    ue4_v = asset.summary.compatible_version
    ue4_14_or_above = ue4_v.major >= 4 and ue4_v.minor >= 14
    if ue4_14_or_above:
        speedtree_wind = f.ReadBool32()
        assert not speedtree_wind

        if v_obj >= 8:
            # TArray<FStaticMaterial> StaticMaterials
            for i in range(f.ReadInt32()):
                mat_interface, mat_slot_name = (asset.DecodePackageIndex(f.ReadInt32()), f.ReadFName(asset.names))
                if editor: imported_mat_slot_name = f.ReadFName(asset.names)
                if v_obj >= 10:
                    initialized, override_densities = (f.ReadBool32(), f.ReadBool32())
                    local_uv_densities = (f.ReadFloat(), f.ReadFloat(), f.ReadFloat(), f.ReadFloat())
                
                if import_materials: mesh.materials.append(TryGetUMaterialImport(mat_interface, mesh=mesh))
    elif import_materials:
        material_props:list[uasset.UProperty] = self.properties.TryGetValue('Materials', [])
        for mat_prop in material_props:
            mesh.materials.append(TryGetUMaterialImport(mat_prop.value, mesh=mesh))

    # remaining is SpeedTree

    if log: print(f"Imported {self.object_name} ({len(mesh.vertices)} Verts, {len(mesh.polygons)} Tris, {len(mesh.materials)} Materials): {(time.time() - t0) * 1000:.2f}ms")
    return mesh
def ImportSkeletalMesh(self:Export, import_materials=True, o=None):
    asset = self.asset
    f = asset.f
    self.ReadProperties(False, False)
    if f.ReadInt32(): self.guid = f.ReadGuid()

    strip_flags = ReadStripFlags(f, asset.summary)
    bounds = f.ReadStructure(uasset.FBoxSphereBounds)

    v_obj = asset.summary.custom_versions.get(v_obj_guid, 0)
    v_tangent = asset.summary.custom_versions.get(v_tang_guid, 0)
    v_ren = asset.summary.custom_versions.get(v_ren_guid, 0)
    v_skel = asset.summary.custom_versions.get(v_skel_guid, 0)

    bmsh = bmesh.new()

    # TArray<FSkeletalMaterial> Materials;
    materials = []
    for i in range(f.ReadInt32()):
        mat_import = asset.DecodePackageIndex(f.ReadInt32())
        materials.append(mat_import)
        assert v_obj < 8 # RefactorMeshEditorMaterials
        if asset.summary.version_ue4 >= 302: shadow_casting = f.ReadBool32() # VER_UE4_MOVE_SKELETALMESH_SHADOWCASTING
        if v_tangent >= 1: recompute_tangent = f.ReadBool32() # RuntimeRecomputeTangent
        assert v_ren < 10 # TextureStreamingMeshUVChannelData

    # FReferenceSkeleton

    #ref_bone_info = # TArray<FMeshBoneInfo>
    ref_bone_info = []
    for i in range(f.ReadInt32()):
        name, i_parent = (f.ReadFName(asset.names), f.ReadInt32())
        if asset.summary.version_ue4 < 310: color = f.ReadStructure(FColor) # VER_UE4_REFERENCE_SKELETON_REFACTOR
        if asset.summary.version_ue4 >= 370: export_name = f.ReadFString() # VER_UE4_STORE_BONE_EXPORT_NAMES
        ref_bone_info.append((name, i_parent))

    ref_bone_pose:list[uasset.FTransform] = f.ReadArray(uasset.FTransform) # TArray<FTransform>
    
    index_to_name = {}
    if asset.summary.version_ue4 >= 310: # VER_UE4_REFERENCE_SKELETON_REFACTOR
        for i in range(f.ReadInt32()):
            key, value = ( f.ReadFName(asset.names), f.ReadInt32() )
            print(f"{value} {key}")
            index_to_name[value] = key
    else:
        for i in range(len(ref_bone_info)): index_to_name[i] = ref_bone_info[i][0]

    mesh = bpy.data.meshes.new(self.object_name) # TODO: oy vey, static mesh doesn't have to create an object
    mesh.name = self.object_name
    o = bpy.data.objects.new(mesh.name, mesh)
    bpy.context.collection.objects.link(o)

    bone_groups:list[bpy.types.VertexGroup] = []
    for i in sorted(index_to_name): bone_groups.append(o.vertex_groups.new(name=index_to_name[i]))
    
    if v_skel < 12: # SplitModelAndRenderData
        # lods = 
        for i_lod in range(f.ReadInt32()):
            # FStaticLODModel4
            lod_strip_flags = ReadStripFlags(f, asset.summary)

            has_cloth_data = False

            # FSkelMeshSection4 sections
            sections = []
            for i_sect in range(f.ReadInt32()):
                sect_strip_flags = ReadStripFlags(f, asset.summary)
                strip_server = sect_strip_flags.StripForServer()
                i_mat = f.ReadInt16()
                if v_skel < 1: i_chunk = f.ReadInt16() # CombineSectionWithChunk
                if not strip_server:
                    i_base, tri_count = (f.ReadInt32(), f.ReadInt32())
                    sections.append((i_mat, i_base, tri_count))
                if v_skel < 13: tri_sorting = f.ReadUInt8() # RemoveTriangleSorting
                if asset.summary.version_ue4 >= 254: # VER_UE4_APEX_CLOTH
                    if v_skel < 15: disabled = f.ReadBool32() # DeprecateSectionDisabledFlag
                    if v_skel < 14: cloth_section = f.ReadInt16() # RemoveDuplicatedClothingSections
                if asset.summary.version_ue4 >= 280: enable_cloth_lod_depricated = f.ReadUInt8() # VER_UE4_APEX_CLOTH_LOD
                if v_tangent >= 1: recompute_tangent = f.ReadBool32() # RuntimeRecomputeTangent
                if v_tangent >= 2: recompute_tangent_vert_mask_channel = f.ReadUInt8() # RecomputeTangentVertexColorMask
                if v_obj >= 8: cast_shadow = f.ReadBool32() # RefactorMeshEditorMaterials
                if v_skel >= 1: # CombineSectionWithChunk
                    if not strip_server: i_base_vert = f.ReadUInt32()
                    if not sect_strip_flags.StripForEditor(): # TODO
                        if v_skel < 2: raise # CombineSoftAndRigidVerts
                        raise
                    raise
            
            if v_skel < 12: indices = ReadFMultisizeIndexContainer(f, asset.summary) # SplitModelAndRenderData
            else: indices = f.ReadArray(c_uint32)
            
            active_bone_indices = f.ReadArray(c_int16) # Bones with vertices

            assert not (asset.summary.compatible_version.major >= 4 and asset.summary.compatible_version.minor >= 20), "Handle packed normals"

            if v_skel < 1: # CombineSectionWithChunk
                # TArray<FSkelMeshChunk4> Chunks
                for i_chunk in range(f.ReadInt32()):
                    strip_flags = ReadStripFlags(f, asset.summary)
                    if not strip_flags.StripForServer(): base_vert_i = f.ReadInt32()
                    if not strip_flags.StripForEditor():
                        skel_influences = 8 if asset.summary.version_ue4 >= 332 else 4 # VER_UE4_SUPPORT_8_BONE_INFLUENCES_SKELETAL_MESHES
                        # FRigidVertex4 rigid_verts
                        for i in range(f.ReadInt32()):
                            ReadFSkelMeshVertexBase(f, v_ren)
                            uvs, color, i_bone = (f.ReadStructure(FVector2D * 4), f.ReadStructure(FColor), f.ReadUInt8())
                        # FSoftVertex4 soft_verts
                        for i in range(f.ReadInt32()):
                            ReadFSkelMeshVertexBase(f, v_ren)
                            uvs, color = (f.ReadStructure(FVector2D * 4), f.ReadStructure(FColor))
                            assert skel_influences > 4 and skel_influences <= 8
                            bone_indices = f.ReadStructure(c_ubyte * skel_influences)
                            bone_weights = f.ReadStructure(c_ubyte * skel_influences)
                    bone_map, rigid_vert_c, soft_vert_c, max_bone_influences = (f.ReadArray(c_uint16), f.ReadInt32(), f.ReadInt32(), f.ReadInt32())
                    if asset.summary.version_ue4 >= 254: # VER_UE4_APEX_CLOTH
                        cloth_mappings, physical_mesh_verts, physical_mesh_norms = (f.ReadArray(FApexClothPhysToRenderVertData), f.ReadArray(FVector), f.ReadArray(FVector))
                        cloth_asset_i, cloth_submesh_i = (f.ReadInt16(), f.ReadInt16())
                        has_cloth_data |= len(cloth_mappings) > 0
            
            lod_size = f.ReadInt32()
            if not lod_strip_flags.StripForServer(): vert_c = f.ReadInt32()
            required_bones = f.ReadArray(c_int16)
            if not lod_strip_flags.StripForEditor():
                bulk = BulkHeader().Read(f, asset.summary)
                if not (bulk.flags & (0x1 | 0x100)): # BULKDATA_PayloadAtEndOfFile | BULKDATA_PayloadInSeperateFile
                    if bulk.flags & 0x40: f.Seek(bulk.byte_size, mode=io.SEEK_CUR) # BULKDATA_ForceInlinePayload
            if asset.summary.version_ue4 >= 152: mesh_to_import_vert_map, max_import_vert_i = (f.ReadArray(c_int32), f.ReadInt32()) # VER_UE4_ADD_SKELMESH_MESHTOIMPORTVERTEXMAP
            
            vert_weights = []
            spl_norms = []

            if not lod_strip_flags.StripForServer(): # geometry TODO: var?
                uv_c = f.ReadInt32()

                ue_uvs = []
                mdl_uvs = []
                for i_uv in range(uv_c): mdl_uvs.append(bmsh.loops.layers.uv.new(f"UV{i_uv}"))

                if v_skel < 12: # SplitModelAndRenderData
                    # FSkeletalMeshVertexBuffer4 VertexBufferGPUSkin
                    vb_strip = ReadStripFlags(f, asset.summary, 269) # VER_UE4_STATIC_SKELETAL_MESH_SERIALIZATION_FIX
                    uv_c, float_uvs = (f.ReadInt32(), f.ReadBool32())
                    assert uv_c > 0 and uv_c < 32
                    if asset.summary.version_ue4 >= 334 and v_skel < 7: extra_bone_influences = f.ReadBool32() # VER_UE4_SUPPORT_GPUSKINNING_8_BONE_INFLUENCES & UseSeparateSkinWeightBuffer
                    else: extra_bone_influences = False
                    mesh_extension, mesh_origin = (f.ReadStructure(FVector), f.ReadStructure(FVector))
                    skel_infl_c = 8 if extra_bone_influences else 4
                    i_vert = 0

                    vert_type = FVector2D if float_uvs else FMeshUVHalf
                    el_size = f.ReadInt32() # ReadBulkArray
                    for i in range(f.ReadInt32()):
                        n_x, n_z = (f.ReadStructure(FPackedNormal).Unpack(), f.ReadStructure(FPackedNormal).Unpack())

                        if v_skel < 7: # UseSeparateSkinWeightBuffer, FSkinWeightInfo
                            assert skel_infl_c <= 4
                            bone_indices = f.ReadStructure(c_ubyte * skel_infl_c)
                            bone_weights = f.ReadStructure(c_ubyte * skel_infl_c)

                            vert_weights.append((bone_indices, bone_weights))
                            #for i_w in range(skel_infl_c): bone_groups[bone_indices[i_w]].add((i_vert,), bone_weights[i_w] / 255, 'REPLACE')
                        pos = f.ReadStructure(FVector)
                        uvs = f.ReadStructure(vert_type * uv_c)
                        ue_uvs.append(uvs)

                        vert = bmsh.verts.new(Vector((pos.y, pos.x, pos.z)))
                        vert.normal = n_z
                        i_vert += 1
                    
                    if v_skel >= 7: # UseSeparateSkinWeightBuffer
                        raise # FSkinWeightVertexBuffer SkinWeights
                    # TODO: LoadingMesh->bHasVertexColors? 
                    if not lod_strip_flags.StripClassData(1): adj_indices = ReadFMultisizeIndexContainer(f, asset.summary) # CDSF_AdjacencyData
                    if asset.summary.version_ue4 >= 254 and has_cloth_data: raise # VER_UE4_APEX_CLOTH
            
            bmsh.verts.ensure_lookup_table()
            for i in range(0, len(indices), 3):
                face = bmsh.faces.new((
                    bmsh.verts[indices[i+0]],
                    bmsh.verts[indices[i+1]],
                    bmsh.verts[indices[i+2]]
                ))

                n1 = bmsh.verts[indices[i+0]].normal
                n2 = bmsh.verts[indices[i+1]].normal
                n3 = bmsh.verts[indices[i+2]].normal
                spl_norms.append(Vector((n1.y, n1.x, n1.z)))
                spl_norms.append(Vector((n2.y, n2.x, n2.z)))
                spl_norms.append(Vector((n3.y, n3.x, n3.z)))

                loops = face.loops
                for i_uv in range(uv_c):
                    loops[0][mdl_uvs[i_uv]].uv = ue_uvs[indices[i+0]][i_uv].ToFloat2()
                    loops[1][mdl_uvs[i_uv]].uv = ue_uvs[indices[i+1]][i_uv].ToFloat2()
                    loops[2][mdl_uvs[i_uv]].uv = ue_uvs[indices[i+2]][i_uv].ToFloat2()
            
            bmsh.faces.ensure_lookup_table()
            for i_mat, i_base, tri_count in sections:
                i_tri_base = int(i_base/3)
                for i_tri in range(i_tri_base, i_tri_base + tri_count):
                    bmsh.faces[i_tri].material_index = i_mat

            bmsh.to_mesh(mesh)
            #mesh.normals_split_custom_set(spl_norms)
            mesh.use_auto_smooth = True
            mesh.transform(Matrix.Identity(4) * 0.01)

            for poly in mesh.polygons: poly.use_smooth = True

            i_vert = 0
            for bone_indices, bone_weights in vert_weights:
                for i_w in range(skel_infl_c):
                    bone_groups[bone_indices[i_w]].add((i_vert,), bone_weights[i_w] / 255, 'REPLACE')
                i_vert += 1

            if import_materials:
                for mat_imp in materials:
                    mesh.materials.append(TryGetUMaterialImport(mat_imp, mesh=mesh))

            return mesh
    else: raise # TODO
def ImportMeshUAsset(filepath:str, uproject=None, import_materials=True, log=False, o=None):
    asset = UAsset(filepath, uproject=uproject)
    asset.Read(False)
    for export in asset.exports:
        match export.export_class_type:
            case 'StaticMesh': return ImportStaticMesh(export, import_materials, log)
            case 'SkeletalMesh': return ImportSkeletalMesh(export, import_materials, o)
    if log: print(f"\"{filepath}\" Mesh Export Not Found")
    return None
def ImportUMeshAsObject(filepath:str, uproject=None, materials=True):
    o = bpy.data.objects.new("tmp", None)
    bpy.context.collection.objects.link(o)
    mesh = ImportMeshUAsset(filepath, uproject, materials, True, o)
    o.name = mesh.name

def menu_import_umesh(self, context): self.layout.operator(ImportUMesh.bl_idname, text="UE Mesh (.uasset)")
class ImportUMesh(bpy.types.Operator, ImportHelper):
    """Import Unreal Engine Mesh File"""
    bl_idname    = "import.umesh"
    bl_label     = "Import"
    filename_ext = ".uasset"
    filter_glob: StringProperty(default="*.uasset", options={'HIDDEN'}, maxlen=255)
    files:       CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN','SKIP_SAVE'})
    directory:   StringProperty(options={'HIDDEN'})

    materials:   BoolProperty(name="Materials", default=True, description="Import Mesh Materials (this is usually the slowest part).")

    def execute(self, context):
        for file in self.files:
            if file.name != "": ImportUMeshAsObject(self.directory + file.name, materials=self.materials)
        return {'FINISHED'}

reg_classes = ( ImportUMesh, )

def register():
    register_helper.RegisterClasses(reg_classes)
    register_helper.RegisterDrawFnc(bpy.types.TOPBAR_MT_file_import, ImportUMesh, menu_import_umesh)
def unregister():
    register_helper.TryUnregisterClasses(reg_classes)
    register_helper.UnregisterDrawFnc(bpy.types.TOPBAR_MT_file_import, ImportUMesh, menu_import_umesh)

if __name__ != "umesh":
    importlib.reload(uasset)
    importlib.reload(umat)
    unregister()
    register()

    #filepath = r"F:\Projects\Unreal Projects\Assets\Content\ModSci_Engineer\Meshes\SM_Door_Small_A.uasset"
    #filepath = r"F:\Projects\Unreal Projects\Assets\Content\VehicleVarietyPack\Meshes\SM_Truck_Box.uasset"
    #filepath = r"F:\Projects\Unreal Projects\Assets\Content\VehicleVarietyPack\Meshes\SM_Hatchback.uasset"
    #filepath = r"F:\Projects\Unreal Projects\Assets\Content\VehicleVarietyPack\Meshes\SM_Pickup.uasset"
    #filepath = r"F:\Projects\Unreal Projects\Assets\Content\VehicleVarietyPack\Meshes\SM_SUV.uasset"
    #filepath = r"F:\Projects\Unreal Projects\Assets\Content\VehicleVarietyPack\Meshes\SM_SportsCar.uasset"
    #filepath = r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\ModSci_Engineer\Meshes\SM_Door_Small_A.uasset"
    #filepath = r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\VehicleVarietyPack\Meshes\SM_Truck_Box.uasset"
    #filepath = r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\ConstructionMachines\WheelLoader\SM_WheelLoader.uasset"
    #filepath = r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\FPS_Weapon_Bundle\Weapons\Meshes\Accessories\SM_Scope_25x56_X.uasset"
    #filepath = r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\FPS_Weapon_Bundle\Weapons\Meshes\KA74U\SK_KA74U_X.uasset"
    #filepath = r"F:\Projects\Unreal Projects\Assets\Content\FPS_Weapon_Bundle\Weapons\Meshes\KA74U\SK_KA74U_X.uasset"
    filepath = r"C:\Users\jdeacutis\Documents\Unreal Projects\Assets\Content\FPS_Weapon_Bundle\Weapons\Meshes\SMG11\SK_SMG11_Nostock_Y.uasset"

    ImportUMeshAsObject(filepath)

    print("Done")