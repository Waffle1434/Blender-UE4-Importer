bl_info = {
    "name" : "Unreal Importer",
    "author" : "Jason Deacutis",
    "description" : "",
    "blender" : (2, 80, 0),
    "version" : (0, 0, 1),
    "location" : "",
    "warning" : "",
    "category" : "Generic"
}

if "bpy" in locals():
    import importlib
    importlib.reload(import_uasset)
else:
    from . import import_uasset

import bpy

def register():
    print("reg")

def unregister():
    print("unreg")


filepath = r"F:\Art\Assets\Game\Blender UE4 Importer\Samples\Example_Stationary_Test.umap"

import_uasset.LoadUAssetScene(filepath)