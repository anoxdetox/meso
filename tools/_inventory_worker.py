"""Inventory worker: runs INSIDE one headless Blender process (see tools/dump_inventory.py).

    $B -b --factory-startup --python-exit-code 1 --python tools/_inventory_worker.py -- \
        --section global --out <json>
    $B -b --factory-startup --python-exit-code 1 --python tools/_inventory_worker.py -- \
        --section workspace --workspace <name> --strategy direct|premode --out <json>
    $B -b --factory-startup --python-exit-code 1 --python tools/_inventory_worker.py -- \
        --section editors --out <json>

The 'editors' section (Phase 3) records baselines for editors no factory workspace shows
(Sequencer x sequencer_scene x view types, Clip tracking/masking, Graph F-Curves/Drivers, NLA,
Asset Browser, Preferences) by switching the Layout Timeline area's ui_type in this process.

This is a TOOL, not the product recorder (that comes in Phase 3). The fake layout below is generated from
the RNA function table of bpy.types.UILayout, so signatures always match the running Blender
(docs/verified-facts-5.2.md section 4).

Workspace access (docs/header-controls-5.2.md section 5 HAZARD): `window.workspace = ws` does not apply in
`-b` (no event loop, verified: the window stays on 'Layout'), so non-Layout workspaces are reached with
`temp_override(window=..., screen=ws.screens[0])`, which switches workspace AND object mode. Doing that
directly for 'Sculpting' segfaults 5.2.2; the 'premode' strategy first enters the workspace's object_mode
via object.mode_set in Layout, after which the screen override is safe. Only one foreign screen is ever
entered per process.

Active tools: in -b, workspace.tools is empty, so VIEW_3D / IMAGE_EDITOR areas without an active tool get the
GUI-verified default tool set (wm.tool_set_by_id inside that area) and are re-recorded; the headless first
attempt is kept under `tool_init_retry`. With that, every recorded header/tool header/footer matched a GUI
session of the same factory workspaces (except PROPERTIES_HT_header, skipped because ui_scale is 0.0 in -b,
and template_asset_shelf_popover's icon: 'BRUSH_DATA' headless vs a brush preview icon_value in the GUI,
properties_paint_common.py:201).
"""

import inspect
import json
import os
import re
import sys
import types

import bpy

# --------------------------------------------------------------------------------------------------
# helpers

_ADDR = re.compile(r"0x[0-9a-fA-F]+")


def _err(exc):
    msg = "%s: %s" % (type(exc).__name__, exc)
    msg = _ADDR.sub("0x?", msg)
    return msg[:400]


def _rna_name(obj):
    rna = getattr(obj, "bl_rna", None)
    if rna is not None:
        try:
            return rna.identifier
        except Exception:
            pass
    return type(obj).__name__


def _summ(v, depth=0):
    """JSON-safe, deterministic summary of a value (no memory addresses)."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, (set, frozenset)):
        return sorted(_summ(x, depth + 1) for x in v)
    if isinstance(v, (list, tuple)) and depth < 3:
        return [_summ(x, depth + 1) for x in v]
    if isinstance(v, bpy.types.bpy_struct):
        name = getattr(v, "name", None)
        return "<%s%s>" % (_rna_name(v), (" " + name) if isinstance(name, str) and name else "")
    try:
        if len(v) <= 16 and not isinstance(v, (dict,)) and depth < 3:  # mathutils / bpy_prop_array
            return [_summ(x, depth + 1) for x in v]
    except Exception:
        pass
    return "<%s>" % type(v).__name__


def _norm_op(idname):
    """'MOD_OT_x' -> 'mod.x'."""
    if "_OT_" in idname:
        mod, _, name = idname.partition("_OT_")
        return mod.lower() + "." + name
    return idname


def _op_rna(idname):
    mod, _, name = _norm_op(idname).partition(".")
    try:
        m = getattr(bpy.ops, mod)
        if name not in dir(m):  # hasattr() returns a stub for any name (verified-facts section 4)
            return None
        return getattr(m, name).get_rna_type()
    except Exception:
        return None


# --------------------------------------------------------------------------------------------------
# props proxy (operator() return value) -- accepts setattr, reads RNA defaults

class PropsProxy:
    def __init__(self, sink, rna):
        object.__setattr__(self, "_sink", sink)  # dict receiving assignments
        object.__setattr__(self, "_rna", rna)

    def _prop(self, name):
        rna = object.__getattribute__(self, "_rna")
        if rna is None:
            return None
        try:
            return rna.properties.get(name)
        except Exception:
            return None

    def __setattr__(self, name, value):
        object.__getattribute__(self, "_sink")[name] = _summ(value)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        sink = object.__getattribute__(self, "_sink")
        if name in sink:
            return sink[name]
        p = self._prop(name)
        if p is None:
            raise AttributeError(name)
        if p.type == "POINTER":
            sub = sink.setdefault(name, {})
            return PropsProxy(sub, p.fixed_type)
        if p.type == "COLLECTION":
            lst = sink.setdefault(name, [])
            fixed = p.fixed_type

            class _Coll:
                def add(self_inner):
                    d = {}
                    lst.append(d)
                    return PropsProxy(d, fixed)

                def __len__(self_inner):
                    return len(lst)

                def __iter__(self_inner):
                    return iter(())

            return _Coll()
        if getattr(p, "is_array", False) or getattr(p, "array_length", 0):
            try:
                return tuple(p.default_array)
            except Exception:
                pass
        if p.type == "ENUM" and getattr(p, "is_enum_flag", False):
            return set(p.default_flag)
        return getattr(p, "default", None)


# --------------------------------------------------------------------------------------------------
# fake layout generated from UILayout RNA

_LAYOUT_RNA = bpy.types.UILayout.bl_rna
_STATE_DEFAULTS = {}
for _p in _LAYOUT_RNA.properties:
    if _p.identifier == "rna_type":
        continue
    _STATE_DEFAULTS[_p.identifier] = getattr(_p, "default", None)
_STATE_DEFAULTS.update(active=True, enabled=True, direction="HORIZONTAL", scale_x=1.0, scale_y=1.0)

_FUNCS = {}
for _f in _LAYOUT_RNA.functions:
    ins = [p for p in _f.parameters if not p.is_output]
    outs = [p for p in _f.parameters if p.is_output]
    _FUNCS[_f.identifier] = ([p.identifier for p in ins], [(p.identifier, p.type,
                              p.fixed_type.identifier if p.type == "POINTER" else None) for p in outs])

_CONTAINERS = {"row", "column", "column_flow", "grid_flow", "box", "split", "menu_pie"}
_DYNAMIC = {"template_node_asset_menu_items", "template_node_operator_asset_menu_items",
            "template_node_operator_asset_root_items", "template_modifier_asset_menu_items",
            "template_recent_files"}
_OP_KINDS = {"operator", "operator_menu_hold", "operator_menu_enum", "template_popup_confirm", "operator_enum"}
_PROP_KINDS = {"prop", "props_enum", "prop_menu_enum", "prop_with_popover", "prop_with_menu", "prop_tabs_enum",
               "prop_enum", "prop_search", "prop_decorator", "textbox", "textbox_with_state"}


class Log:
    def __init__(self):
        self.records = []
        self.opaque = 0


class FakeLayout:
    def __init__(self, log, parent=None, root_state=None):
        d = self.__dict__
        d["_log"] = log
        d["_parent"] = parent
        d["_state"] = {}
        if root_state:
            d["_state"].update(root_state)

    # state with inheritance -----------------------------------------------------------------
    def _get_state(self, name):
        lay = self
        while lay is not None:
            st = lay.__dict__["_state"]
            if name in st:
                return st[name]
            lay = lay.__dict__["_parent"]
        return _STATE_DEFAULTS.get(name)

    def __setattr__(self, name, value):
        self.__dict__["_state"][name] = value

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name in _STATE_DEFAULTS:
            return self._get_state(name)
        if name in _FUNCS:
            return types.MethodType(_make_func(name), self)
        log = self.__dict__["_log"]

        def _opaque(*args, **kw):
            log.opaque += 1
            log.records.append({"kind": "opaque", "name": name})
            return FakeLayout(log, self)
        return _opaque

    def _child(self):
        return FakeLayout(self.__dict__["_log"], self)

    def _emit(self, rec):
        if not self._get_state("enabled"):
            rec["enabled"] = False
        if not self._get_state("active"):
            rec["active"] = False
        self.__dict__["_log"].records.append(rec)
        return rec


def _label_for_menu(mid, text):
    if text:
        return text
    cls = getattr(bpy.types, mid, None)
    return getattr(cls, "bl_label", None) if cls is not None else None


def _label_for_panel(pid, text):
    if text:
        return text
    cls = getattr(bpy.types, pid, None)
    return getattr(cls, "bl_label", None) if cls is not None else None


def _make_func(fname):
    in_names, outs = _FUNCS[fname]

    def fn(self, *args, **kw):
        a = dict(zip(in_names, args))
        extra = list(args[len(in_names):])
        a.update(kw)
        if fname in _CONTAINERS:
            return self._child()
        if fname in ("panel", "panel_prop"):
            return (self._child(), self._child())
        if fname in ("icon", "enum_item_icon"):
            return 0
        if fname in ("enum_item_name", "enum_item_description"):
            try:
                p = a["data"].bl_rna.properties[a["property"]]
                it = p.enum_items[a["identifier"]]
                return it.name if fname == "enum_item_name" else it.description
            except Exception:
                return ""
        rec = {"kind": fname}
        text = a.get("text")
        if text not in (None, ""):
            rec["text"] = text
        if "icon" in a and a["icon"] not in (None, "", "NONE"):
            rec["icon"] = a["icon"]
        ret = None
        if fname in _OP_KINDS:
            op = _norm_op(a.get("operator", ""))
            rec["id"] = op
            rna = _op_rna(op)
            if rna is None:
                rec["missing_op"] = True
            elif fname != "operator_enum":
                rec["label"] = text or rna.name
            if "property" in a:
                rec["prop"] = a["property"]
            if fname == "operator_menu_hold":
                rec["menu"] = a.get("menu")
            if a.get("depress"):
                rec["depress"] = True
            oc = self._get_state("operator_context")
            if oc != self.__dict__["_log"].root_oc:
                rec["operator_context"] = oc
            if fname != "operator_enum":
                sink = {}
                ret = PropsProxy(sink, rna)
                rec["props"] = sink
        elif fname in _PROP_KINDS:
            data = a.get("data")
            rec["owner"] = _rna_name(data) if data is not None else None
            try:
                path = data.path_from_id() if data is not None else ""
                if path:
                    rec["owner_path"] = _ADDR.sub("0x?", path)
            except Exception:
                pass
            prop = a.get("property")
            rec["prop"] = prop
            try:
                p = data.bl_rna.properties.get(prop)
                if p is not None:
                    rec["ptype"] = p.type + ("_FLAG" if getattr(p, "is_enum_flag", False) else "")
                    rec["label"] = text or p.name
            except Exception:
                pass
            for k in ("panel", "menu", "value"):
                if k in a:
                    rec[k] = a[k]
            for k in ("expand", "icon_only", "toggle", "index", "text_align"):
                if k in a and a[k] not in (None, False, -1, 0):
                    rec[k] = _summ(a[k])
            if fname == "prop_search":
                rec["search_owner"] = _rna_name(a.get("search_data"))
                rec["search_prop"] = a.get("search_property")
        elif fname in ("menu", "menu_contents"):
            mid = a.get("menu")
            rec["id"] = mid
            rec["exists"] = hasattr(bpy.types, mid) if isinstance(mid, str) else False
            rec["label"] = _label_for_menu(mid, text)
        elif fname == "popover":
            pid = a.get("panel")
            rec["id"] = pid
            rec["label"] = _label_for_panel(pid, text)
        elif fname == "popover_group":
            for k in ("space_type", "region_type", "context", "category"):
                rec[k] = a.get(k)
        elif fname == "separator":
            for k in ("factor", "type"):
                if k in a:
                    rec[k] = _summ(a[k])
        elif fname in ("context_pointer_set", "context_string_set"):
            rec["name"] = a.get("name")
            rec["value"] = _summ(a.get("data", a.get("value")))
        elif fname.startswith("template_"):
            rec["kind"] = "template"
            rec["name"] = fname
            if fname in _DYNAMIC:
                rec["dynamic"] = True
            if fname == "template_asset_shelf_popover":
                rec["id"] = a.get("asset_shelf")
            elif "property" in a and "data" in a:
                rec["owner"] = _rna_name(a["data"])
                rec["prop"] = a["property"]
            if fname == "template_recent_files":
                ret = 0
            elif fname == "template_popup_confirm":
                ret = PropsProxy({}, None)
        elif fname in ("label", "link", "progress"):
            if fname == "link":
                rec["url"] = a.get("url")
        if extra:
            rec["extra_args"] = len(extra)
        self._emit(rec)
        return ret

    fn.__name__ = fname
    return fn


# --------------------------------------------------------------------------------------------------
# FakeSelf (inspect.getattr_static over the MRO, descriptor-aware binding)

_C_DESCRIPTORS = ("getset_descriptor", "member_descriptor", "method_descriptor", "wrapper_descriptor",
                  "builtin_function_or_method", "classmethod_descriptor")


class FakeSelf:
    def __init__(self, cls, layout, is_popover=False):
        d = self.__dict__
        d["_cls"] = cls
        d["layout"] = layout
        d["is_popover"] = is_popover
        d["text"] = ""
        d["custom_data"] = None
        try:
            bid = inspect.getattr_static(cls, "bl_idname")
            if not isinstance(bid, str):
                raise AttributeError
        except AttributeError:
            bid = cls.bl_rna.identifier
        d["bl_idname"] = bid

    def __getattr__(self, name):
        cls = self.__dict__["_cls"]
        if name == "bl_rna":
            return cls.bl_rna
        try:
            v = inspect.getattr_static(cls, name)
        except AttributeError:
            raise AttributeError(name) from None
        tname = type(v).__name__
        if tname in _C_DESCRIPTORS:
            raise AttributeError(name)
        if isinstance(v, staticmethod):
            return v.__func__
        if isinstance(v, classmethod):
            return types.MethodType(v.__func__, cls)
        if isinstance(v, property):
            return v.fget(self)
        if isinstance(v, types.FunctionType):
            return types.MethodType(v, self)
        return v

    def __setattr__(self, name, value):
        self.__dict__[name] = value


def record_draw(cls, context, root_oc="INVOKE_REGION_WIN"):
    """Record cls.draw into a flat record list. Returns dict(records, errors, opaque, extended)."""
    log = Log()
    log.root_oc = root_oc
    layout = FakeLayout(log, root_state={"operator_context": root_oc})
    fake = FakeSelf(cls, layout, is_popover=issubclass(cls, bpy.types.Panel))
    out = {"errors": []}
    draw = inspect.getattr_static(cls, "draw", None)
    if draw is None:
        out["errors"].append("no draw")
        out["records"] = []
        return out
    if isinstance(draw, (staticmethod, classmethod)):
        draw = draw.__func__
    funcs = getattr(draw, "_draw_funcs", None)
    if funcs is not None:
        out["extended"] = [getattr(f, "__module__", "?") + "." + getattr(f, "__qualname__", "?") for f in funcs]
    else:
        funcs = [draw]
    poll = getattr(cls, "poll", None)
    if poll is not None:
        try:
            out["poll"] = bool(poll(context))
        except Exception as ex:
            out["poll"] = "error: " + _err(ex)
    for f in funcs:
        try:
            f(fake, context)
        except Exception as ex:
            out["errors"].append("%s: %s" % (getattr(f, "__qualname__", "?"), _err(ex)))
        layout.operator_context = root_oc
    out["records"] = log.records
    out["opaque"] = log.opaque
    if not out["errors"]:
        del out["errors"]
    return out


# --------------------------------------------------------------------------------------------------
# class tables

def _all_types():
    names = sorted(dir(bpy.types))
    res = {}
    for n in names:
        try:
            res[n] = getattr(bpy.types, n)
        except Exception:
            pass
    return res


def header_classes():
    """{(space_type, region_type): [class names]} for registered Header subclasses."""
    res = {}
    for n, c in _all_types().items():
        if isinstance(c, type) and issubclass(c, bpy.types.Header) and c is not bpy.types.Header:
            st = getattr(c, "bl_space_type", None)
            rt = getattr(c, "bl_region_type", "HEADER") or "HEADER"
            res.setdefault((st, rt), []).append(n)
    return res


def section_global():
    types_ = _all_types()
    mt = sorted(n for n in types_ if "_MT_" in n)
    menus = sorted(n for n in mt if isinstance(types_[n], type) and issubclass(types_[n], bpy.types.Menu))
    panels = {"HEADER": [], "TOOL_HEADER": []}
    for n, c in types_.items():
        if isinstance(c, type) and issubclass(c, bpy.types.Panel) and c is not bpy.types.Panel:
            rt = getattr(c, "bl_region_type", None)
            if rt in panels:
                panels[rt].append(getattr(c, "bl_idname", n) or n)
    for v in panels.values():
        v.sort()
    hc = header_classes()
    headers = sorted(({"class": n, "space_type": st, "region_type": rt}
                      for (st, rt), ns in hc.items() for n in ns), key=lambda d: d["class"])

    out = {
        "blender": {
            "version_string": bpy.app.version_string,
            "version": list(bpy.app.version),
            "build_hash": bpy.app.build_hash.decode() if isinstance(bpy.app.build_hash, bytes) else str(bpy.app.build_hash),
            "python": sys.version.split()[0],
            "factory_startup": bool(bpy.app.factory_startup),
            "background": bool(bpy.app.background),
        },
        "types": {
            "mt_names": mt,
            "mt_count": len(mt),
            "mt_menu_subclasses": menus,
            "mt_menu_subclass_count": len(menus),
            "mt_not_menu": sorted(set(mt) - set(menus)),
            "header_panels": panels,
            "header_panel_counts": {k: len(v) for k, v in panels.items()},
            "header_classes": headers,
        },
        "workspaces_alphabetical": [ws.name for ws in bpy.data.workspaces],
        "workspace_object_modes": {ws.name: ws.object_mode for ws in bpy.data.workspaces},
    }

    # keymaps -------------------------------------------------------------------------------------
    wm = bpy.context.window_manager
    km_out = {}
    km_out["before_keyconfig_set"] = {"active": wm.keyconfigs.active.name,
                                      "n_keymaps": len(wm.keyconfigs.active.keymaps),
                                      "n_items": sum(len(k.keymap_items) for k in wm.keyconfigs.active.keymaps)}
    preset = os.path.join(bpy.utils.system_resource("SCRIPTS"), "presets", "keyconfig", "Blender.py")
    km_out["preset"] = "<SCRIPTS>/presets/keyconfig/Blender.py"
    try:
        km_out["keyconfig_set_result"] = bool(bpy.utils.keyconfig_set(preset))
    except Exception as ex:
        km_out["keyconfig_set_result"] = "error: " + _err(ex)
    kc = wm.keyconfigs.active
    km_out["active"] = kc.name
    km_out["spacebar_action"] = getattr(getattr(kc, "preferences", None), "spacebar_action", None)
    km_out["keyconfigs"] = {k.name: {"n_keymaps": len(k.keymaps),
                                     "n_items": sum(len(m.keymap_items) for m in k.keymaps)}
                            for k in wm.keyconfigs}
    kms, space_items = [], []
    for km in kc.keymaps:
        kms.append({"name": km.name, "space_type": km.space_type, "region_type": km.region_type,
                    "is_modal": bool(km.is_modal), "n_items": len(km.keymap_items)})
        for kmi in km.keymap_items:
            if kmi.type != "SPACE":
                continue
            try:
                item = {"keymap": km.name, "idname": kmi.idname, "value": kmi.value,
                        "shift": kmi.shift, "ctrl": kmi.ctrl, "alt": kmi.alt, "oskey": kmi.oskey,
                        "any": kmi.any, "active": kmi.active, "repeat": kmi.repeat,
                        "key_modifier": kmi.key_modifier}
                if km.is_modal:
                    item["propvalue"] = kmi.propvalue
                props = {}
                p = kmi.properties
                if p is not None:
                    for rp in p.bl_rna.properties:
                        ident = rp.identifier
                        if ident == "rna_type":
                            continue
                        try:
                            if p.is_property_set(ident):
                                props[ident] = _summ(getattr(p, ident))
                        except Exception:
                            pass
                item["properties"] = props
            except Exception as ex:
                item = {"keymap": km.name, "error": _err(ex)}
            space_items.append(item)
    km_out["keymaps"] = kms
    km_out["n_keymaps"] = len(kms)
    km_out["n_items"] = sum(k["n_items"] for k in kms)
    km_out["space_items"] = space_items
    km_out["n_space_items"] = len(space_items)
    out["keymaps"] = km_out

    # global topbar menus (area=None is safe per verified-facts section 4 design point 4)
    try:
        with bpy.context.temp_override(window=bpy.context.window):
            out["topbar_editor_menus"] = record_draw(bpy.types.TOPBAR_MT_editor_menus, bpy.context)
    except Exception as ex:
        out["topbar_editor_menus"] = {"errors": [_err(ex)]}

    # probe (last, after all recording): does `window.workspace = ws` apply in -b? (5.2.2: no)
    try:
        win = bpy.context.window
        target = next(ws for ws in bpy.data.workspaces if ws != win.workspace)
        win.workspace = target
        out["window_workspace_assign_applied_in_background"] = (win.workspace == target)
    except Exception as ex:
        out["window_workspace_assign_applied_in_background"] = "error: " + _err(ex)
    return out


# --------------------------------------------------------------------------------------------------
# per-workspace screen recording

_REC_REGIONS = ("HEADER", "TOOL_HEADER", "FOOTER")


def _space_flags(space):
    flags = {}
    try:
        for p in space.bl_rna.properties:
            if p.identifier.startswith("show_region_") and p.type == "BOOLEAN":
                flags[p.identifier] = bool(getattr(space, p.identifier))
    except Exception:
        pass
    return flags


def _find_editor_menus(recs):
    ids = []
    for r in recs:
        if r.get("kind") in ("menu_contents", "menu") and str(r.get("id", "")).endswith("editor_menus"):
            if r["id"] not in ids:
                ids.append(r["id"])
    return ids


def record_area(window, screen, area, use_screen, hc, only_regions=_REC_REGIONS):
    ui_scale = bpy.context.preferences.system.ui_scale
    res = {"regions_recorded": {}}
    for rtype in only_regions:
        region = next((r for r in area.regions if r.type == rtype), None)
        if region is None:
            continue
        classes = hc.get((area.type, rtype), [])
        per = {}
        for cname in classes:
            cls = getattr(bpy.types, cname)
            if cname == "PROPERTIES_HT_header" and not ui_scale:
                per[cname] = {"skipped": True,
                              "errors": ["ZeroDivisionError: ui_scale is 0.0 in -b --factory-startup "
                                         "(draw divides by ui_scale); skipped"]}
                continue
            kw = dict(window=window, area=area, region=region)
            if use_screen:
                kw["screen"] = screen
            try:
                with bpy.context.temp_override(**kw):
                    rec = record_draw(cls, bpy.context)
                    mts = _find_editor_menus(rec["records"])
                    if mts:
                        rec["editor_menus"] = {}
                        for mt in mts:
                            mcls = getattr(bpy.types, mt, None)
                            if mcls is None:
                                rec["editor_menus"][mt] = {"errors": ["not in bpy.types"]}
                            else:
                                rec["editor_menus"][mt] = record_draw(mcls, bpy.context)
            except Exception as ex:
                rec = {"errors": ["override/record: " + _err(ex)]}
            per[cname] = rec
        res["regions_recorded"][rtype] = per
    return res


def describe_area(area):
    d = {"type": area.type, "ui_type": area.ui_type,
         "x": area.x, "y": area.y, "width": area.width, "height": area.height,
         "show_menus": bool(area.show_menus),
         "regions": [{"type": r.type, "x": r.x, "y": r.y, "width": r.width, "height": r.height}
                     for r in area.regions]}
    sp = area.spaces.active
    if sp is not None:
        d["space"] = _rna_name(sp)
        d["space_flags"] = _space_flags(sp)
        for attr in ("mode", "ui_mode", "view_type", "display_mode", "tree_type", "browse_mode"):
            v = getattr(sp, attr, None)
            if isinstance(v, str):
                d.setdefault("space_state", {})[attr] = v
    return d


_MODE_TO_SET = {"OBJECT": "OBJECT", "EDIT_MESH": "EDIT", "SCULPT": "SCULPT", "PAINT_WEIGHT": "WEIGHT_PAINT",
                "PAINT_VERTEX": "VERTEX_PAINT", "PAINT_TEXTURE": "TEXTURE_PAINT"}


def _v3d_override(window, screen):
    v3d = next((a for a in screen.areas if a.type == "VIEW_3D"), None)
    if v3d is None:
        return None, None
    win = next((r for r in v3d.regions if r.type == "WINDOW"), None)
    return v3d, win


def _mode_set(window, screen, mode):
    v3d, win = _v3d_override(window, screen)
    with bpy.context.temp_override(window=window, area=v3d, region=win):
        r = bpy.ops.object.mode_set(mode=mode)
        return sorted(r), bpy.context.mode


def _active_tool(window, screen, area, use_screen):
    from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    kw = dict(window=window, area=area, region=region)
    if use_screen:
        kw["screen"] = screen
    with bpy.context.temp_override(**kw):
        t = ToolSelectPanelHelper.tool_active_from_context(bpy.context)
        return (t.idname if t is not None else None), kw


# Default tool per (editor, mode) as observed in a GUI session (Blender 5.2.2, --factory-startup, verified by
# recording every factory workspace in a real window): WM_toolsystem_init sets these when a workspace/mode is
# activated by the event loop. In -b, workspace.tools stays empty for workspaces/modes entered only via
# temp_override (and even for Layout OBJECT), so the tool header loses the active tool's settings (e.g. the
# select_box `mode` buttons) and VIEW3D_HT_header's SCULPT branch raises on `tool.use_brushes`
# (space_view3d.py:971). Only (editor, mode) pairs verified in the GUI are listed; others are left alone.
_GUI_DEFAULT_TOOL_VIEW3D = {"OBJECT": "builtin.select_box", "EDIT_MESH": "builtin.select_box",
                            "SCULPT": "builtin.brush", "PAINT_WEIGHT": "builtin.brush",
                            "PAINT_VERTEX": "builtin.brush", "PAINT_TEXTURE": "builtin.brush"}
_GUI_DEFAULT_TOOL_IMAGE = {"UV": "builtin.select_box", "VIEW": "builtin.sample", "PAINT": "builtin.brush"}


def _gui_default_tool(area):
    if area.type == "VIEW_3D":
        return _GUI_DEFAULT_TOOL_VIEW3D.get(bpy.context.mode)
    if area.type == "IMAGE_EDITOR":
        if area.ui_type == "UV":
            return _GUI_DEFAULT_TOOL_IMAGE["UV"]
        return _GUI_DEFAULT_TOOL_IMAGE.get(getattr(area.spaces.active, "ui_mode", None))
    return None


def _tool_fixup(window, screen, area, use_screen, hc, d, only_regions=_REC_REGIONS):
    """If the area has no active tool (headless artefact, see above), set the GUI default tool inside this
    area and re-record. The first attempt is kept under `tool_init_retry`."""
    try:
        tool, kw = _active_tool(window, screen, area, use_screen)
    except Exception as ex:
        d["active_tool"] = "error: " + _err(ex)
        return
    d["active_tool"] = tool
    default = _gui_default_tool(area)
    if tool is not None or default is None:
        return
    first = d.get("regions_recorded", {})
    fix = {"reason": "no active tool in -b (workspace.tools empty); set the GUI default tool and re-recorded",
           "headless_active_tool": None, "tool_set": default,
           "first_attempt_errors": {"%s/%s" % (rt, c): r["errors"] for rt, per in sorted(first.items())
                                    for c, r in sorted(per.items()) if r.get("errors") and not r.get("skipped")},
           "first_attempt_n_records": {"%s/%s" % (rt, c): len(r.get("records", [])) for rt, per in
                                       sorted(first.items()) for c, r in sorted(per.items())}}
    try:
        # -b skips ToolSelectPanelHelper.register(), so tool keymaps are still functions and activating a tool
        # with a fallback (IMAGE_EDITOR UV select_box) raises TypeError in _activate_by_item; register_ensure()
        # is the API meant for background mode.
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
        tcls = ToolSelectPanelHelper._tool_class_from_space_type(area.type)
        if tcls is not None:
            tcls.register_ensure()
        with bpy.context.temp_override(**kw):
            fix["tool_set_by_id"] = sorted(bpy.ops.wm.tool_set_by_id(name=default))
        after = _active_tool(window, screen, area, use_screen)[0]
        fix["active_tool_after"] = after
        d["active_tool"] = after
        d.update(record_area(window, screen, area, use_screen, hc, only_regions=only_regions))
    except Exception as ex:
        fix["error"] = _err(ex)
    d["tool_init_retry"] = fix


def section_workspace(name, strategy):
    window = bpy.context.window
    out = {"name": name, "strategy": strategy}
    ws = bpy.data.workspaces.get(name)
    if ws is None:
        out["error"] = "workspace not found"
        return out
    out["object_mode"] = ws.object_mode
    screen = ws.screens[0]
    out["screen"] = screen.name
    is_layout = window.screen == screen
    hc = header_classes()

    if not is_layout and strategy == "premode":
        want = {"EDIT": "EDIT", "SCULPT": "SCULPT", "WEIGHT_PAINT": "WEIGHT_PAINT", "VERTEX_PAINT": "VERTEX_PAINT",
                "TEXTURE_PAINT": "TEXTURE_PAINT", "POSE": "POSE", "OBJECT": "OBJECT"}.get(ws.object_mode)
        if want and want != "OBJECT":
            try:
                out["premode"] = {"mode_set": want, "result": _mode_set(window, window.screen, want)}
            except Exception as ex:
                out["premode"] = {"mode_set": want, "error": _err(ex)}

    sys.stdout.flush()
    areas = []
    try:
        ctx_kw = dict(window=window) if is_layout else dict(window=window, screen=screen)
        with bpy.context.temp_override(**ctx_kw):
            out["context_mode"] = bpy.context.mode
            out["context_workspace"] = bpy.context.workspace.name
            for area in screen.areas:
                try:
                    d = describe_area(area)
                    d.update(record_area(window, screen, area, not is_layout, hc))
                    if area.type in ("VIEW_3D", "IMAGE_EDITOR"):
                        _tool_fixup(window, screen, area, not is_layout, hc, d)
                except Exception as ex:
                    d = {"type": getattr(area, "type", "?"), "error": _err(ex)}
                areas.append(d)
    except Exception as ex:
        out["error"] = "screen override: " + _err(ex)
    out["areas"] = areas

    if is_layout:
        out["view3d_modes"] = record_view3d_modes(window, screen, hc)
    return out


def record_view3d_modes(window, screen, hc):
    res = {}
    v3d, _win = _v3d_override(window, screen)
    if v3d is None:
        return {"error": "no VIEW_3D area"}
    for mode, set_to in _MODE_TO_SET.items():
        entry = {}
        try:
            entry["mode_set_result"], entry["context_mode"] = _mode_set(window, screen, set_to)
        except Exception as ex:
            entry["mode_set_error"] = _err(ex)
        try:
            with bpy.context.temp_override(window=window):
                entry.update(record_area(window, screen, v3d, False, hc, only_regions=("HEADER", "TOOL_HEADER")))
                _tool_fixup(window, screen, v3d, False, hc, entry, only_regions=("HEADER", "TOOL_HEADER"))
            mt = entry["regions_recorded"].get("HEADER", {}).get("VIEW3D_HT_header", {}) \
                .get("editor_menus", {}).get("VIEW3D_MT_editor_menus", {})
            entry["editor_menu_ids"] = [r["id"] for r in mt.get("records", []) if r.get("kind") == "menu"]
            entry["editor_menu_labels"] = [r.get("label") for r in mt.get("records", []) if r.get("kind") == "menu"]
            entry["editor_menu_templates"] = [r["name"] for r in mt.get("records", []) if r.get("kind") == "template"]
        except Exception as ex:
            entry["error"] = _err(ex)
        res[mode] = entry
    try:
        _mode_set(window, screen, "OBJECT")
    except Exception:
        pass
    return res


# --------------------------------------------------------------------------------------------------
# editors section (Phase 3): baselines for editors no factory workspace shows, recorded in Layout
# by switching ONE area's ui_type inside this throw-away process (never a foreign screen).

# (key, ui_type, space setup) in output order. Setup keys: view_type / mode (space attrs),
# sequencer_scene (True -> workspace.sequencer_scene = the scene, False -> None).
_SEQ_VIEWS = ("SEQUENCER", "PREVIEW", "SEQUENCER_PREVIEW")
EDITOR_VARIANTS = tuple(
    [("SEQUENCE_EDITOR/%s/%s" % ("scene" if sc else "no_scene", vt), "SEQUENCE_EDITOR",
      {"view_type": vt, "sequencer_scene": sc}) for sc in (False, True) for vt in _SEQ_VIEWS]
    + [("CLIP_EDITOR/TRACKING", "CLIP_EDITOR", {"mode": "TRACKING"}),
       ("CLIP_EDITOR/MASK", "CLIP_EDITOR", {"mode": "MASK"}),
       ("FCURVES", "FCURVES", {}),
       ("DRIVERS", "DRIVERS", {}),
       ("NLA_EDITOR", "NLA_EDITOR", {}),
       ("ASSETS", "ASSETS", {}),
       ("PREFERENCES", "PREFERENCES", {})])

# The area whose ui_type is switched (factory Layout: the bottom Timeline, wide and short).
_EDITOR_HOST_UI_TYPE = "TIMELINE"


def _editor_menu_summary(d):
    """Contextual menu ids / labels of an area recording (the HEADER class's editor_menus
    expansion), for the inventory summary."""
    out = {}
    for cname, rec in sorted(d.get("regions_recorded", {}).get("HEADER", {}).items()):
        for mt, mrec in sorted(rec.get("editor_menus", {}).items()):
            recs = mrec.get("records", [])
            out[mt] = {"ids": [r["id"] for r in recs if r.get("kind") == "menu"],
                       "labels": [r.get("label") for r in recs if r.get("kind") == "menu"],
                       "n_errors": len(mrec.get("errors", []) or [])}
    return out


def section_editors():
    window = bpy.context.window
    screen = window.screen
    hc = header_classes()
    out = {"host_ui_type": _EDITOR_HOST_UI_TYPE, "workspace": window.workspace.name,
           "editors": {}}
    area = next((a for a in screen.areas if a.ui_type == _EDITOR_HOST_UI_TYPE), None)
    if area is None:
        out["error"] = "no %s area in the startup screen" % _EDITOR_HOST_UI_TYPE
        return out
    workspace = window.workspace
    old_seq = getattr(workspace, "sequencer_scene", None)
    try:
        for key, ui_type, setup in EDITOR_VARIANTS:
            entry = {"ui_type": ui_type, "setup": dict(setup)}
            try:
                area.ui_type = ui_type
                space = area.spaces.active
                if "sequencer_scene" in setup:
                    workspace.sequencer_scene = bpy.context.scene if setup["sequencer_scene"] else None
                for attr in ("view_type", "mode"):
                    if attr in setup:
                        setattr(space, attr, setup[attr])
                if ui_type == "ASSETS" and getattr(space, "params", None) is None:
                    entry["skipped"] = "SpaceFileBrowser.params is None in -b (no file list yet)"
                    out["editors"][key] = entry
                    continue
                with bpy.context.temp_override(window=window, area=area):
                    entry["context_sequencer_scene"] = (
                        getattr(bpy.context, "sequencer_scene", None) is not None)
                entry.update(describe_area(area))
                entry.update(record_area(window, screen, area, False, hc))
                if area.type in ("VIEW_3D", "IMAGE_EDITOR"):
                    _tool_fixup(window, screen, area, False, hc, entry)
                entry["contextual_menus"] = _editor_menu_summary(entry)
            except Exception as ex:
                entry["error"] = _err(ex)
            out["editors"][key] = entry
    finally:
        try:
            workspace.sequencer_scene = old_seq
        except Exception:
            pass
        area.ui_type = _EDITOR_HOST_UI_TYPE
    return out


# --------------------------------------------------------------------------------------------------

def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = {}
    it = iter(argv)
    for a in it:
        if a.startswith("--"):
            args[a[2:]] = next(it, "")
    out_path = args["out"]
    section = args.get("section", "workspace")
    if section == "global":
        data = section_global()
    elif section == "editors":
        data = section_editors()
    else:
        data = section_workspace(args["workspace"], args.get("strategy", "premode"))
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, sort_keys=True, indent=1)
    print("INVENTORY_WORKER_OK", section, args.get("workspace", ""))
    sys.stdout.flush()


main()
