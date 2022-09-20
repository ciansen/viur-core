import json
import logging
import typing
from collections import OrderedDict
from viur.core import bones, utils, config
from viur.core import db
from viur.core.skeleton import SkeletonInstance
from viur.core.utils import currentRequest
from viur.core.i18n import translate
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union


def prepareDeriveName(deriver: str, sizeDict: typing.Dict[str, typing.Any]) -> str:
    """We need a valid filename from one of the derived image spec

    TODO: change deriver globally to an class with this method
    """

    file_extension = sizeDict.get("fileExtension", "webp")
    target_name = ""
    if "width" in sizeDict and "height" in sizeDict:
        width = sizeDict["width"]
        height = sizeDict["height"]
        target_name = f"{deriver}-{width}-{height}.{file_extension}"
    elif "width" in sizeDict:
        width = sizeDict["width"]
        # target_name = "thumbnail-w%s.%s" % (width, file_extension)
        target_name = f"{deriver}-w{width}.{file_extension}"
    return target_name


class CustomJsonEncoder(json.JSONEncoder):
    """
        This custom JSON-Encoder for this json-render ensures that translations are evaluated and can be dumped.
    """

    def default(self, o: Any) -> Any:
        if isinstance(o, translate):
            return str(o)
        elif isinstance(o, datetime):
            return o.isoformat()
        elif isinstance(o, db.Key):
            return db.encodeKey(o)
        return json.JSONEncoder.default(self, o)


class DefaultRender(object):
    kind = "json"

    def __init__(self, parent=None, *args, **kwargs):
        super(DefaultRender, self).__init__(*args, **kwargs)
        self.parent = parent

    def renderBoneStructure(self, bone: bones.BaseBone) -> Dict[str, Any]:
        """
        Renders the structure of a bone.

        This function is used by `renderSkelStructure`.
        can be overridden and super-called from a custom renderer.

        :param bone: The bone which structure should be rendered.
        :type bone: Any bone that inherits from :class:`server.bones.BaseBone`.

        :return: A dict containing the rendered attributes.
        """

        # Base bone contents.
        ret = {
            "descr": str(bone.descr),
            "type": bone.type,
            "required": bone.required,
            "params": bone.params,
            "visible": bone.visible,
            "readonly": bone.readOnly,
            "unique": bone.unique.method.value if bone.unique else False,
            "languages": bone.languages,
            "emptyValue": bone.getEmptyValue()
        }
        if bone.multiple and isinstance(bone.multiple, bones.MultipleConstraints):
            ret["multiple"] = {
                "minAmount": bone.multiple.minAmount,
                "maxAmount": bone.multiple.maxAmount,
                "preventDuplicates": bone.multiple.preventDuplicates,
            }
        else:
            ret["multiple"] = bone.multiple

        if bone.type == "relational" or bone.type.startswith("relational."):
            ret.update({
                "type": "%s.%s" % (bone.type, bone.kind),
                "module": bone.module,
                "format": bone.format,
                "using": self.renderSkelStructure(bone.using()) if bone.using else None,
                "relskel": self.renderSkelStructure(bone._refSkelCache())
            })

        elif bone.type == "record" or bone.type.startswith("record."):
            ret.update({
                "format": bone.format,
                "using": self.renderSkelStructure(bone.using())
            })

        elif bone.type == "select" or bone.type.startswith("select."):
            ret.update({
                "values": [(k, str(v)) for k, v in bone.values.items()],
            })

        elif bone.type == "date" or bone.type.startswith("date."):
            ret.update({
                "date": bone.date,
                "time": bone.time
            })

        elif bone.type == "numeric" or bone.type.startswith("numeric."):
            ret.update({
                "precision": bone.precision,
                "min": bone.min,
                "max": bone.max
            })

        elif bone.type == "text" or bone.type.startswith("text."):
            ret.update({
                "validHtml": bone.validHtml,
                "languages": bone.languages
            })

        elif bone.type == "str" or bone.type.startswith("str."):
            ret.update({
                "languages": bone.languages
            })

        return ret

    def renderSkelStructure(self, skel: SkeletonInstance) -> Optional[List[Tuple[str, Dict[str, Any]]]]:
        """
        Dumps the structure of a :class:`viur.core.skeleton.Skeleton`.

        :param skel: Skeleton which structure will be processed.

        :returns: The rendered dictionary.
        """
        if isinstance(skel, dict):
            return None
        res = OrderedDict()
        for key, bone in skel.items():
            res[key] = self.renderBoneStructure(bone)
        return [(key, val) for key, val in res.items()]

    def renderSingleBoneValue(self, value: Any,
                              bone: bones.BaseBone,
                              skel: SkeletonInstance,
                              key,
                              deriveSpec: typing.Dict = None
                              ) -> Union[Dict, str, None]:
        """
        Renders the value of a bone.

        This function is used by :func:`collectSkelData`.
        It can be overridden and super-called from a custom renderer.

        :param bone: The bone which value should be rendered.
        :type bone: Any bone that inherits from :class:`server.bones.base.BaseBone`.

        :return: A dict containing the rendered attributes.
        """
        if isinstance(bone, bones.RelationalBone):
            if isinstance(value, dict):
                # logging.debug("renderSingleBoneValue: %r, %r, %r, %r", bone.descr, value, key, deriveSpec)
                return {
                    "dest": self.renderSkelValues(value["dest"], injectDownloadURL=isinstance(bone, bones.FileBone), deriveSpec=deriveSpec),
                    "rel": (self.renderSkelValues(value["rel"], injectDownloadURL=isinstance(bone, bones.FileBone), deriveSpec=deriveSpec)
                            if value["rel"] else None),
                }
        elif isinstance(bone, bones.RecordBone):
            return self.renderSkelValues(value, deriveSpec=deriveSpec)
        elif isinstance(bone, bones.PasswordBone):
            return ""
        else:
            return value
        return None

    def renderBoneValue(self, bone: bones.BaseBone, skel: SkeletonInstance, key: str, deriveSpec: typing.Dict = None) -> Union[List, Dict, None]:
        # logging.debug("renderBoneValue: %r, %r", key, deriveSpec)
        boneVal = skel[key]
        if not deriveSpec and hasattr(bone, "derive"):
            deriveSpec = {"boneName": key, "spec": bone.derive}

        if bone.languages and bone.multiple:
            res = {}
            for language in bone.languages:
                if boneVal and language in boneVal and boneVal[language]:
                    res[language] = [self.renderSingleBoneValue(v, bone, skel, key, deriveSpec=deriveSpec) for v in boneVal[language]]
                else:
                    res[language] = []
        elif bone.languages:
            res = {}
            for language in bone.languages:
                if boneVal and language in boneVal and boneVal[language]:
                    res[language] = self.renderSingleBoneValue(boneVal[language], bone, skel, key, deriveSpec=deriveSpec)
                else:
                    res[language] = None
        elif bone.multiple:
            res = [self.renderSingleBoneValue(v, bone, skel, key, deriveSpec=deriveSpec) for v in boneVal] if boneVal else None
        else:
            res = self.renderSingleBoneValue(boneVal, bone, skel, key, deriveSpec=deriveSpec)
        return res

    def renderSkelValues(self, skel: SkeletonInstance, injectDownloadURL: bool = False, deriveSpec: typing.Dict = None) -> Optional[Dict]:
        """
        Prepares values of one :class:`viur.core.skeleton.Skeleton` or a list of skeletons for output.

        :param skel: Skeleton which contents will be processed.
        """
        # logging.debug("renderSkelValues: %r", deriveSpec)
        if skel is None:
            return None
        elif isinstance(skel, dict):
            return skel
        res = {}
        for key, bone in skel.items():
            res[key] = self.renderBoneValue(bone, skel, key, deriveSpec=deriveSpec)
        if injectDownloadURL and "dlkey" in skel and "name" in skel:
            res["downloadUrl"] = utils.downloadUrlFor(
                skel["dlkey"],
                skel["name"],
                derived=False,
                expires=config.conf["viur.render.json.downloadUrlExpiration"])
        if deriveSpec and "dlkey" in skel:
            widths = [item["width"] for item in deriveSpec["spec"]["thumbnail"]]
            res["srcSet"] = utils.srcSetFor(skel, 0, widths)
        #     derivePayload = deriveSpec["spec"]
        #     for deriver, deriveConfigs in derivePayload.items():
        #         srcSet = list()
        #         for item in deriveConfigs:
        #             if item.get("renderer", {}).get(self.kind, True):  # FIXME: this should be only conditionally activated
        #                 filename = prepareDeriveName(deriver, item)
        #                 url = utils.downloadUrlFor(skel["dlkey"], filename, True, 0)
        #                 srcSet.append(f"{url} {item['width']}w")
        #                 res["derived"]["files"][filename]["downloadUrl"] = url
        #         res["srcSet"] = ", ".join(srcSet)
        return res

    def renderEntry(self, skel: SkeletonInstance, actionName, params=None):
        if isinstance(skel, list):
            vals = [self.renderSkelValues(x) for x in skel]
            struct = self.renderSkelStructure(skel[0])
            errors = None
        elif isinstance(skel, SkeletonInstance):
            vals = self.renderSkelValues(skel)
            struct = self.renderSkelStructure(skel)
            errors = [{"severity": x.severity.value, "fieldPath": x.fieldPath, "errorMessage": x.errorMessage,
                       "invalidatedFields": x.invalidatedFields} for x in skel.errors]
        else:  # Hopefully we can pass it directly...
            vals = skel
            struct = None
            errors = None
        res = {
            "values": vals,
            "structure": struct,
            "errors": errors,
            "action": actionName,
            "params": params
        }
        currentRequest.get().response.headers["Content-Type"] = "application/json"
        return json.dumps(res, cls=CustomJsonEncoder)

    def view(self, skel: SkeletonInstance, action="view", params=None, *args, **kwargs):
        return self.renderEntry(skel, action, params)

    def add(self, skel: SkeletonInstance, action="add", params=None, **kwargs):
        return self.renderEntry(skel, action, params)

    def edit(self, skel: SkeletonInstance, action="edit", params=None, **kwargs):
        return self.renderEntry(skel, action, params)

    def list(self, skellist, action="list", params=None, **kwargs):
        res = {}
        skels = []

        if skellist:
            for skel in skellist:
                skels.append(self.renderSkelValues(skel))

            res["cursor"] = skellist.getCursor()
            res["structure"] = self.renderSkelStructure(skellist.baseSkel)
        else:
            res["structure"] = None
            res["cursor"] = None

        res["skellist"] = skels
        res["action"] = action
        res["params"] = params
        currentRequest.get().response.headers["Content-Type"] = "application/json"
        return json.dumps(res, cls=CustomJsonEncoder)

    def editSuccess(self, skel: SkeletonInstance, params=None, **kwargs):
        return self.renderEntry(skel, "editSuccess", params)

    def addSuccess(self, skel: SkeletonInstance, params=None, **kwargs):
        return self.renderEntry(skel, "addSuccess", params)

    def addDirSuccess(self, rootNode, path, dirname, params=None, *args, **kwargs):
        return json.dumps("OKAY")

    def listRootNodes(self, rootNodes, tpl=None, params=None):
        for rn in rootNodes:
            rn["key"] = db.encodeKey(rn["key"])
        return json.dumps(rootNodes)

    def listRootNodeContents(self, subdirs, entrys, tpl=None, params=None, **kwargs):
        res = {
            "subdirs": subdirs
        }

        skels = []

        for skel in entrys:
            skels.append(self.renderSkelValues(skel))

        res["entrys"] = skels
        return json.dumps(res, cls=CustomJsonEncoder)

    def renameSuccess(self, rootNode, path, src, dest, params=None, *args, **kwargs):
        return json.dumps("OKAY")

    def copySuccess(self, srcrepo, srcpath, name, destrepo, destpath, type, deleteold, params=None, *args, **kwargs):
        return json.dumps("OKAY")

    def deleteSuccess(self, skel: SkeletonInstance, params=None, *args, **kwargs):
        return json.dumps("OKAY")

    def reparentSuccess(self, obj, tpl=None, params=None, *args, **kwargs):
        return json.dumps("OKAY")

    def setIndexSuccess(self, obj, tpl=None, params=None, *args, **kwargs):
        return json.dumps("OKAY")

    def cloneSuccess(self, tpl=None, params=None, *args, **kwargs):
        return json.dumps("OKAY")

    def checker(self, dlkey: str, filename: str) -> str:
        """This should be handled otherwise, but here we get from outside valid download urls for known dl keys :P

        :param dlkey:
        :param filename:
        :return:

        FIXME: security and this should not be needed...
        """
        logging.debug("checker: %r, %r", dlkey, filename)
        return utils.downloadUrlFor(dlkey, filename, derived=True, expires=0)
