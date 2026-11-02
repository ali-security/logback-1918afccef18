#!/usr/bin/env python3
"""Print one line per skipped test, with its reason, from surefire XML reports.

Surefire only prints a per-module "Skipped: N" count. This reads
<module>/target/surefire-reports/TEST-*.xml and prints
    SKIPPED <class>#<method>: <reason>
using the report's <skipped message=...> when present, otherwise the
@Disabled / assume line found in the test source (upstream's own skip).
"""
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."


def find_source(module, classname):
    rel = classname.split("$")[0].replace(".", "/") + ".java"
    path = os.path.join(module, "src", "test", "java", rel)
    return path if os.path.isfile(path) else None


def reason_from_source(path, method):
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
    if method:
        pat = re.compile(r"\bvoid\s+" + re.escape(method) + r"\s*\(")
        for i, line in enumerate(lines):
            if pat.search(line):
                for j in range(max(0, i - 6), i):
                    if "@Disabled" in lines[j] or "@Ignore" in lines[j]:
                        return "upstream %s at %s:%d" % (lines[j].strip(), rel, j + 1)
                for j in range(i, min(len(lines), i + 15)):
                    if re.search(r"\bassume(True|False|That)\s*\(", lines[j]):
                        return "assumption not met on this JVM: %s at %s:%d" % (
                            lines[j].strip(), rel, j + 1)
                break
    for j, line in enumerate(lines):
        # class-level annotations sit at column 0
        if line.startswith("@Disabled") or line.startswith("@Ignore"):
            return "upstream class-level %s at %s:%d" % (line.strip(), rel, j + 1)
    return "skipped by upstream annotation in %s" % rel


total = 0
modules = {}
for report in sorted(glob.glob(os.path.join(ROOT, "*", "target", "surefire-reports", "TEST-*.xml"))):
    module = os.path.dirname(os.path.dirname(os.path.dirname(report)))
    mname = os.path.basename(module)
    try:
        tree = ET.parse(report)
    except ET.ParseError:
        continue
    for tc in tree.getroot().iter("testcase"):
        sk = tc.find("skipped")
        if sk is None:
            continue
        cls = tc.get("classname") or ""
        name = (tc.get("name") or "").split("(")[0].split("[")[0]
        msg = (sk.get("message") or "").strip()
        if not msg:
            src = find_source(module, cls)
            msg = reason_from_source(src, name) if src else "no message in report"
        print("SKIPPED %s#%s [%s]: %s" % (cls, name, mname, msg))
        modules[mname] = modules.get(mname, 0) + 1
        total += 1

# Modules whose pom sets <disableXmlReport>true</disableXmlReport> (logback-access)
# write no TEST-*.xml; list the upstream @Disabled tests in their sources instead,
# minus the classes the module pom already excludes from surefire.
for rdir in sorted(glob.glob(os.path.join(ROOT, "*", "target", "surefire-reports"))):
    module = os.path.dirname(os.path.dirname(rdir))
    if glob.glob(os.path.join(rdir, "TEST-*.xml")):
        continue
    mname = os.path.basename(module)
    pom_excludes = set()
    pom = os.path.join(module, "pom.xml")
    if os.path.isfile(pom):
        with open(pom, encoding="utf-8", errors="replace") as fh:
            pom_excludes = set(re.findall(r"<exclude>\*\*/([\w$]+)\.java</exclude>", fh.read()))
    tdir = os.path.join(module, "src", "test", "java")
    for src in sorted(glob.glob(os.path.join(tdir, "**", "*.java"), recursive=True)):
        base = os.path.splitext(os.path.basename(src))[0]
        if base in pom_excludes or not re.search(r"(^Test|Test$|Tests$|TestCase$)", base):
            continue
        with open(src, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        rel = os.path.relpath(src, ROOT).replace(os.sep, "/")
        cls = os.path.relpath(src, tdir)[:-5].replace(os.sep, ".")
        for j, line in enumerate(lines):
            s = line.strip()
            if not (s.startswith("@Disabled") or s.startswith("@Ignore")):
                continue
            if not line.startswith(" "):
                target = ""
                why = "upstream class-level %s at %s:%d" % (s, rel, j + 1)
            else:
                target = ""
                for k in range(j + 1, min(len(lines), j + 6)):
                    mm = re.search(r"\bvoid\s+(\w+)\s*\(", lines[k])
                    if mm:
                        target = mm.group(1)
                        break
                why = "upstream %s at %s:%d" % (s, rel, j + 1)
            print("SKIPPED %s#%s [%s, no XML report; from source]: %s" % (cls, target, mname, why))
            modules[mname] = modules.get(mname, 0) + 1
            total += 1

for m in sorted(modules):
    print("SKIP-REPORT module %s: %d skipped" % (m, modules[m]))
print("SKIP-REPORT TOTAL skipped tests listed: %d" % total)
print("SKIP-REPORT note: Maven's 'Skipped: N' summaries count a test once per surefire "
      "execution; logback-classic-blackbox runs the same classes in two executions "
      "(default-test and singleJVM), so each of its skipped tests above appears twice "
      "in those summaries but once in this list.")
