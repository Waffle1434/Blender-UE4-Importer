import bpy

persist_vars = bpy.app.driver_namespace

def RegisterClasses(classes:list):
    for cls in classes: bpy.utils.register_class(cls)
def TryUnregisterClasses(classes:list):
    for cls in classes:
        try: bpy.utils.unregister_class(cls) 
        except: pass

def RegisterDrawFnc(event, op:bpy.types.Operator, fnc):
    id = event.bl_rna.name
    handles = persist_vars.get(id, {})
    if op.bl_idname not in handles:
        event.append(fnc)
        handles[op.bl_idname] = fnc
        persist_vars[id] = handles
def UnregisterDrawFnc(event, op:bpy.types.Operator, fnc):
    handles:dict = persist_vars.get(event.bl_rna.name, {})
    handle = handles.pop(op.bl_idname, None)
    if handle:
        try: event.remove(handle)
        except: pass
    try: event.remove(fnc)
    except: pass