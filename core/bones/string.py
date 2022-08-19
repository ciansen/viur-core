from viur.core.bones.base import BaseBone, ReadFromClientError, ReadFromClientErrorSeverity
from viur.core.config import conf
from viur.core.utils import currentLanguage
from viur.core import db, request, utils
from typing import Dict, List, Optional, Union
from viur.core.utils import currentLanguage
import logging


class StringBone(BaseBone):
    type = "str"

    def __init__(
        self,
        *,
        caseSensitive: bool = True,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.caseSensitive = caseSensitive

    def singleValueSerialize(self, value, skel: 'SkeletonInstance', name: str, parentIndexed: bool):
        if not self.caseSensitive and parentIndexed:
            return {"val": value, "idx": value.lower() if isinstance(value, str) else None}
        return value

    def singleValueUnserialize(self, value):
        if isinstance(value, dict) and "val" in value:
            return value["val"]
        elif value:
            return str(value)
        else:
            return ""

    def getEmptyValue(self):
        return ""

    def singleValueFromClient(self, value, skel, name, origData):
        value = utils.escapeString(value)
        err = self.isInvalid(value)
        if not err:
            return utils.escapeString(value), None
        return self.getEmptyValue(), [ReadFromClientError(ReadFromClientErrorSeverity.Invalid, err)]


    def buildDBFilter(
        self,
        name: str,
        skel: 'viur.core.skeleton.SkeletonInstance',
        dbFilter: db.Query,
        rawFilter: Dict,
        prefix: Optional[str] = None
    ) -> db.Query:
        if name not in rawFilter and not any(
            [(x.startswith(name + "$") or x.startswith(name + ".")) for x in rawFilter.keys()]
        ):
            return super().buildDBFilter(name, skel, dbFilter, rawFilter, prefix)

        if not self.languages:
            namefilter = name
        else:
            lang = None
            for key in rawFilter.keys():
                if key.startswith("%s." % name):
                    langStr = key.replace("%s." % name, "")
                    if langStr in self.languages:
                        lang = langStr
                        break
            if not lang:
                lang = currentLanguage.get()  # currentSession.getLanguage()
                if not lang or not lang in self.languages:
                    lang = self.languages[0]
            namefilter = "%s.%s" % (name, lang)

        if name + "$lk" in rawFilter:  # Do a prefix-match
            if not self.caseSensitive:
                dbFilter.filter((prefix or "") + namefilter + ".idx >=", str(rawFilter[name + "$lk"]).lower())
                dbFilter.filter((prefix or "") + namefilter + ".idx <",
                                str(rawFilter[name + "$lk"] + u"\ufffd").lower())
            else:
                dbFilter.filter((prefix or "") + namefilter + " >=", str(rawFilter[name + "$lk"]))
                dbFilter.filter((prefix or "") + namefilter + " <", str(rawFilter[name + "$lk"] + u"\ufffd"))

        if name + "$gt" in rawFilter:  # All entries after
            if not self.caseSensitive:
                dbFilter.filter((prefix or "") + namefilter + ".idx >", str(rawFilter[name + "$gt"]).lower())
            else:
                dbFilter.filter((prefix or "") + namefilter + " >", str(rawFilter[name + "$gt"]))

        if name + "$lt" in rawFilter:  # All entries before
            if not self.caseSensitive:
                dbFilter.filter((prefix or "") + namefilter + ".idx <", str(rawFilter[name + "$lt"]).lower())
            else:
                dbFilter.filter((prefix or "") + namefilter + " <", str(rawFilter[name + "$lt"]))

        if name in rawFilter:  # Normal, strict match
            if not self.caseSensitive:
                dbFilter.filter((prefix or "") + namefilter + ".idx", str(rawFilter[name]).lower())
            else:
                dbFilter.filter((prefix or "") + namefilter, str(rawFilter[name]))

        return dbFilter

    def buildDBSort(
        self,
        name: str,
        skel: 'viur.core.skeleton.SkeletonInstance',
        dbFilter: db.Query,
        rawFilter: Dict
    ) -> Optional[db.Query]:
        if "orderby" in rawFilter and (rawFilter["orderby"] == name or (
            isinstance(rawFilter["orderby"], str) and rawFilter["orderby"].startswith(
            "%s." % name) and self.languages)):
            if self.languages:
                lang = None
                if rawFilter["orderby"].startswith("%s." % name):
                    lng = rawFilter["orderby"].replace("%s." % name, "")
                    if lng in self.languages:
                        lang = lng
                if lang is None:
                    lang = currentLanguage.get()  # currentSession.getLanguage()
                    if not lang or not lang in self.languages:
                        lang = self.languages[0]
                if self.caseSensitive:
                    prop = "%s.%s" % (name, lang)
                else:
                    prop = "%s.%s.idx" % (name, lang)
            else:
                if self.caseSensitive:
                    prop = name
                else:
                    prop = name + ".idx"
            if "orderdir" in rawFilter and rawFilter["orderdir"] == "1":
                order = (prop, db.SortOrder.Descending)
            elif "orderdir" in rawFilter and rawFilter["orderdir"] == "2":
                order = (prop, db.SortOrder.InvertedAscending)
            elif "orderdir" in rawFilter and rawFilter["orderdir"] == "3":
                order = (prop, db.SortOrder.InvertedDescending)
            else:
                order = (prop, db.SortOrder.Ascending)
            inEqFilter = [x for x in dbFilter.queries.filters.keys() if  # FIXME: This will break on multi queries
                          (">" in x[-3:] or "<" in x[-3:] or "!=" in x[-4:])]
            if inEqFilter:
                inEqFilter = inEqFilter[0][: inEqFilter[0].find(" ")]
                if inEqFilter != order[0]:
                    logging.warning("I fixed you query! Impossible ordering changed to %s, %s" % (inEqFilter, order[0]))
                    dbFilter.order(inEqFilter, order)
                else:
                    dbFilter.order(order)
            else:
                dbFilter.order(order)
        return dbFilter

    def getSearchTags(self, skeletonValues, name):
        res = set()
        value = skeletonValues[name]
        if not value:
            return res
        if self.languages and isinstance(value, dict):
            if self.multiple:
                for lang in value.values():
                    if not lang:
                        continue
                    for val in lang:
                        for line in str(val).splitlines():
                            for key in line.split(" "):
                                res.add(key.lower())
            else:
                for lang in value.values():
                    for line in str(lang).splitlines():
                        for key in line.split(" "):
                            res.add(key.lower())
        else:
            if self.multiple:
                for val in value:
                    for line in str(val).splitlines():
                        for key in line.split(" "):
                            res.add(key.lower())
            else:
                for line in str(value).splitlines():
                    for key in line.split(" "):
                        res.add(key.lower())
        return res

    def getUniquePropertyIndexValues(self, skel, name: str) -> List[str]:
        if self.languages:
            # Not yet implemented as it's unclear if we should keep each language distinct or not
            raise NotImplementedError()

        return super().getUniquePropertyIndexValues(skel, name)