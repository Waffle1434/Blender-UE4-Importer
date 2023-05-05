bl_info = {
    "name" : "Unreal Engine 4",
    "author" : "Waffle1434",
    "description" : "Import UE4 meshes, materials, & maps.",
    "blender" : (2, 80, 0),
    "version" : (0, 0, 1),
    "location" : "",
    "warning" : "",
    "category" : "Import-Export"
}

import os, sys

cur_dir = os.path.dirname(__file__)
if cur_dir not in sys.path: sys.path.append(cur_dir)

import umap, umesh, umat

def register():
    umat.register()
    umesh.register()
    umap.register()

def unregister():
    umat.unregister()
    umesh.unregister()
    umap.unregister()
