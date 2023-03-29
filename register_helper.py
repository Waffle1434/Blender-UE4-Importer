import bpy

persist_vars = bpy.app.driver_namespace

def RegisterClasses(classes:list):
    for cls in classes: bpy.utils.register_class(cls)
def TryUnregisterClasses(classes:list):
    for cls in classes:
        try: bpy.utils.unregister_class(cls)
        except: pass

def RegisterOperatorItem(event, op:bpy.types.Operator, text):
    fnc = lambda self, context : self.layout.operator(op.bl_idname, text=text)
    id = event.bl_rna.name
    handles = persist_vars.get(id, {})
    event.append(fnc)
    handles[id] = fnc
    persist_vars[id] = handles
def RemoveOperatorItem(event, op:bpy.types.Operator):
    handles = persist_vars.get(event.bl_rna.name, {})
    handle = handles.get(op.bl_idname)
    if handle:
        try: event.remove(handle)
        except: pass