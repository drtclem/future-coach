"""Namespaces and small helpers shared by ingestion, the safety filter and tests."""

import re

from pyoxigraph import NamedNode

BASE = "https://example.org/future-coach/kg"
FC = BASE + "#"
FCA = BASE + "/anatomy/"
FCE = BASE + "/equipment/"
FCP = BASE + "/pattern/"
FCL = BASE + "/load/"
FCC = BASE + "/condition/"
FCR = BASE + "/rule/"
FCF = BASE + "/family/"
FCX = BASE + "/exercise/"
FCM = BASE + "/muscle/"
FCG = BASE + "/region/"
SKOS = "http://www.w3.org/2004/02/skos/core#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
XSD = "http://www.w3.org/2001/XMLSchema#"

KG1 = NamedNode(BASE + "/graph/domain")  # named graph for the domain KG

PREFIXES = f"""
PREFIX fc: <{FC}>
PREFIX fca: <{FCA}>
PREFIX fce: <{FCE}>
PREFIX fcp: <{FCP}>
PREFIX fcl: <{FCL}>
PREFIX fcc: <{FCC}>
PREFIX fcr: <{FCR}>
PREFIX fcf: <{FCF}>
PREFIX fcx: <{FCX}>
PREFIX fcm: <{FCM}>
PREFIX fcg: <{FCG}>
PREFIX skos: <{SKOS}>
"""


def slug(label: str) -> str:
    """'lower push - squat - box/partial' -> 'lower-push-squat-box-partial'."""
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def local(iri: str) -> str:
    """Last path segment or fragment of an IRI, for readable traces."""
    return re.split(r"[/#]", iri)[-1]
