#!/usr/bin/env python
"""Update conda packages on anaconda.org with latest versions for multiple platforms.

"""
import os
import re
import subprocess
import sys
import itertools
import argparse

import toolz as tz
import yaml


CONFIG = {
    "remote_user": "bioconda",
    "remote_repo": "bioconda",
    "numpy": "19",
    "uses_python": yaml.load(open('uses_python.yaml')),
}

# Add targets depending on detected current OS
if sys.platform == "darwin":
    CONFIG['targets'] = ['osx-64']
elif sys.platform in ['linux', 'linux2']:
    CONFIG['targets'] = ['linux-64']
else:
    raise ValueError("%s not in [linux, linux2, darwin]: can't determine OS" % sys.platform)

CUSTOM_TARGETS = {
    "hap.py": ["linux-64"]}

def main(pkgs, force_build=True):
    config = CONFIG
    subprocess.check_call(["conda", "config", "--add", "channels", config["remote_repo"]])
    if not pkgs:
        pkgs = sorted([x for x in os.listdir(os.getcwd()) if os.path.isdir(x)])
    for name in pkgs:
        meta_file = os.path.join(name, "meta.yaml")
        if os.path.exists(meta_file):
            version, build = _meta_to_version(meta_file)
            needs_build = _needs_upload(name, version, build, config)
            print("Need to build these packages: {0}".format(needs_build))
            if needs_build or force_build:
                _build_and_upload(name, needs_build, config, _should_convert(os.path.join(name, "build.sh")))

def _build_and_upload(name, platforms, config, do_convert):
    """Build package for the latest versions and upload on all platforms.
    """
    python_versions = CONFIG.get('uses_python', {name: None}).get(name)
    if python_versions is None:
        python_args = [[]]
    else:
        python_args = [['--python=%s' % i] for i in python_versions]

    for python_arg in python_args:
        fname = subprocess.check_output(["conda", "build", "--numpy", config["numpy"], "--output", name] + python_arg).strip()
        cur_platform = os.path.split(os.path.dirname(fname))[-1]
        if not os.path.exists(fname):
            subprocess.check_call(["conda", "build", "--numpy", config["numpy"], "--no-anaconda-upload", name] + python_arg)
        for platform in platforms:
            out = ""
            if platform == cur_platform:
                plat_fname = fname
            elif do_convert:
                plat_fname = fname.replace("/%s/" % cur_platform, "/%s/" % platform)
                out_dir = os.path.dirname(os.path.dirname(plat_fname))
                if not os.path.exists(out_dir):
                    os.makedirs(out_dir)
                if not os.path.exists(plat_fname):
                    out = subprocess.check_output(["conda", "convert", fname, "-o", out_dir, "-p", platform],
                                                  stderr=subprocess.STDOUT)
            else:
                plat_fname = None

            if plat_fname and os.path.exists(plat_fname):
                subprocess.check_call(["anaconda", "upload", "-u", config["remote_user"], plat_fname])
            else:
                if not out.find("WARNING") >= 0 and not out.find("has C extensions, skipping") >= 0:
                    raise IOError("Failed to create file for %s on %s" % (name, platform))
                else:
                    print "Unable to prepare %s for %s because it contains compiled code" % (name, platform)

def _needs_upload(name, version, build, config):
    """Check if we need to upload libraries for the current package and version.
    """
    pat_np = re.compile("%s-(?P<version>[\d\.a-zA-Z]+)-np(?P<numpy>\d+)py(?P<py>\d+)_?(?P<build>\d+).tar.*" % name)
    pat_py = re.compile("%s-(?P<version>[\d\.a-zA-Z]+)-py(?P<py>\d+)_?(?P<build>\d+).tar.*" % name)
    pat = re.compile("%s-(?P<version>[\d\.a-zA-Z]+).*_?(?P<build>\d+).tar.*" % name)
    try:
        info = subprocess.check_output(["anaconda", "show", "%s/%s/%s" % (config["remote_user"], name, version)])
    # no version found
    except subprocess.CalledProcessError:
        info = ""
    cur_packages = []
    for line in (x for x in info.split("\n") if x.strip().startswith("+")):
        plat, fname = os.path.split(line.strip().split()[-1])
        m = pat_np.search(fname)
        has_numpy = True
        has_python = True
        if not m:
            m = pat_py.search(fname)
            has_numpy = False
            print(name, version, build, config)
            print('py version %s' % m.group('py'))
            if not m:
                m = pat.search(fname)
                has_python = False

        cur_version = m.group("version")
        cur_build = m.group("build")
        numpy = m.group("numpy") if has_numpy else ""
        py = m.group("py") if has_python else None
        py_targets = config['uses_python'].get(name, [None])
        py_targets = [str(i).replace('.', '') for i in py_targets]
        if (
            str(version) == str(cur_version) and
            int(cur_build) == int(build) and (not has_numpy or numpy == config["numpy"]) and
            (not has_python or py in py_targets)
        ):
            cur_packages.append((plat, py))
    if name in CUSTOM_TARGETS:
        return sorted(list(set(CUSTOM_TARGETS[name]) - set(cur_packages)))
    else:
        return sorted(list(set(itertools.product(config["targets"], py_targets)) - set(cur_packages)))

def _meta_to_version(in_file):
    """Extract version information from meta description file.
    """
    with open(in_file) as in_handle:
        config = yaml.safe_load(in_handle)
    return (tz.get_in(["package", "version"], config),
            tz.get_in(["build", "number"], config, 0))

def _should_convert(build_file):
    """Only try to do conversion on Python packages, we check for pure python later
    """
    if os.path.exists(build_file):
        with open(build_file) as in_handle:
            if in_handle.read().find("setup.py install") > 0:
                return True
    return False

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument('packages', nargs="+", help="Package to build")
    ap.add_argument('--force-build', action='store_true', help='Force local build even though the latest version already exists on binstar')
    args = ap.parse_args()
    main(args.packages, force_build=args.force_build)
