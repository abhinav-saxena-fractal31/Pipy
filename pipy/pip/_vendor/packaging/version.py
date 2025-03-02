# This file is dual licensed under the terms of the Apache License, Version
# 2.0, and the BSD License. See the LICENSE file in the root of this repository
# for complete details.
from __future__ import absolute_import, division, print_function

import collections
import itertools
import re

from ._structures import Infinity
from typing import Tuple, Optional, Union


__all__ = [
    "parse", "Version", "LegacyVersion", "InvalidVersion", "VERSION_PATTERN"
]


_Version = collections.namedtuple(
    "_Version",
    ["epoch", "release", "dev", "pre", "post", "local"],
)


def parse(version):
    """
    Parse the given version string and return either a :class:`Version` object
    or a :class:`LegacyVersion` object depending on if the given version is
    a valid PEP 440 version or a legacy version.
    """
    try:
        return Version(version)
    except InvalidVersion:
        return LegacyVersion(version)


class InvalidVersion(ValueError):
    """
    An invalid version was found, users should refer to PEP 440.
    """


class _BaseVersion(object):

    def __hash__(self):
        return hash(self._key)

    def __lt__(self, other):
        return self._compare(other, lambda s, o: s < o)

    def __le__(self, other):
        return self._compare(other, lambda s, o: s <= o)

    def __eq__(self, other):
        return self._compare(other, lambda s, o: s == o)

    def __ge__(self, other):
        return self._compare(other, lambda s, o: s >= o)

    def __gt__(self, other):
        return self._compare(other, lambda s, o: s > o)

    def __ne__(self, other):
        return self._compare(other, lambda s, o: s != o)

    def _compare(self, other, method):
        if not isinstance(other, _BaseVersion):
            return NotImplemented

        return method(self._key, other._key)


class LegacyVersion(_BaseVersion):

    def __init__(self, version):
        self._version = str(version)
        self._key = _legacy_cmpkey(self._version)

    def __str__(self):
        return self._version

    def __repr__(self):
        return "<LegacyVersion({0})>".format(repr(str(self)))

    @property
    def public(self):
        return self._version

    @property
    def base_version(self):
        return self._version

    @property
    def local(self):
        return None

    @property
    def is_prerelease(self):
        return False

    @property
    def is_postrelease(self):
        return False


_legacy_version_component_re = re.compile(
    r"(\d+ | [a-z]+ | \.| -)", re.VERBOSE,
)

_legacy_version_replacement_map = {
    "pre": "c", "preview": "c", "-": "final-", "rc": "c", "dev": "@",
}
def _replace_legacy_component(component):
    return _legacy_version_replacement_map.get(component, component)


def _parse_version_parts(s):
    """Parse the version string into individual version parts.

    Args:
        s (str): The version string to parse.

    Yields:
        str: Individual version parts.
    """
    for part in _legacy_version_component_re.split(s):
        part = _replace_legacy_component(part)

        if not part or part == ".":
            continue

        if part[:1] in "0123456789":
            # pad for numeric comparison
            yield part.zfill(8)
        else:
            yield "*" + part

    # ensure that alpha/beta/candidate are before final
    yield "*final"


def _legacy_cmpkey(version: str) -> tuple:
    """
    Return a tuple representing the comparison key for a legacy version.

    Args:
        version (str): The version string.

    Returns:
        tuple: The comparison key for the version.

    """

    def extract_parts(part):
        # remove "-" before a prerelease tag
        if part < "*final":
            while parts and parts[-1] == "*final-":
                parts.pop()

        # remove trailing zeros from each series of numeric parts
        while parts and parts[-1] == "00000000":
            parts.pop()

        parts.append(part)

    epoch = -1

    parts = []
    for part in _parse_version_parts(version.lower()):
        if part.startswith("*"):
            extract_parts(part)
        else:
            extract_parts(part)
    parts = tuple(parts)

    return epoch, parts

# Deliberately not anchored to the start and end of the string, to make it
# easier for 3rd party code to reuse
VERSION_PATTERN = r"""
    v?
    (?:
        (?:(?P<epoch>[0-9]+)!)?                           # epoch
        (?P<release>[0-9]+(?:\.[0-9]+)*)                  # release segment
        (?P<pre>                                          # pre-release
            [-_\.]?
            (?P<pre_l>(a|b|c|rc|alpha|beta|pre|preview))
            [-_\.]?
            (?P<pre_n>[0-9]+)?
        )?
        (?P<post>                                         # post release
            (?:-(?P<post_n1>[0-9]+))
            |
            (?:
                [-_\.]?
                (?P<post_l>post|rev|r)
                [-_\.]?
                (?P<post_n2>[0-9]+)?
            )
        )?
        (?P<dev>                                          # dev release
            [-_\.]?
            (?P<dev_l>dev)
            [-_\.]?
            (?P<dev_n>[0-9]+)?
        )?
    )
    (?:\+(?P<local>[a-z0-9]+(?:[-_\.][a-z0-9]+)*))?       # local version
"""


class Version(_BaseVersion):

    _regex = re.compile(
        r"^\s*" + VERSION_PATTERN + r"\s*$",
        re.VERBOSE | re.IGNORECASE,
    )

    def __init__(self, version):
        # Validate the version and parse it into pieces
        match = self._regex.search(version)
        if not match:
            raise InvalidVersion("Invalid version: '{0}'".format(version))

        # Store the parsed out pieces of the version
        self._version = _Version(
            epoch=int(match.group("epoch")) if match.group("epoch") else 0,
            release=tuple(int(i) for i in match.group("release").split(".")),
            pre=_parse_letter_version(
                match.group("pre_l"),
                match.group("pre_n"),
            ),
            post=_parse_letter_version(
                match.group("post_l"),
                match.group("post_n1") or match.group("post_n2"),
            ),
            dev=_parse_letter_version(
                match.group("dev_l"),
                match.group("dev_n"),
            ),
            local=_parse_local_version(match.group("local")),
        )

        # Generate a key which will be used for sorting
        self._key = _cmpkey(
            self._version.epoch,
            self._version.release,
            self._version.pre,
            self._version.post,
            self._version.dev,
            self._version.local,
        )

    def __repr__(self):
        return "<Version({0})>".format(repr(str(self)))

    def __str__(self):
        parts = []

        # Epoch
        if self._version.epoch != 0:
            parts.append("{0}!".format(self._version.epoch))

        # Release segment
        parts.append(".".join(str(x) for x in self._version.release))

        # Pre-release
        if self._version.pre is not None:
            parts.append("".join(str(x) for x in self._version.pre))

        # Post-release
        if self._version.post is not None:
            parts.append(".post{0}".format(self._version.post[1]))

        # Development release
        if self._version.dev is not None:
            parts.append(".dev{0}".format(self._version.dev[1]))

        # Local version segment
        if self._version.local is not None:
            parts.append(
                "+{0}".format(".".join(str(x) for x in self._version.local))
            )

        return "".join(parts)

    @property
    def public(self):
        return str(self).split("+", 1)[0]

    @property
    def base_version(self):
        parts = []

        # Epoch
        if self._version.epoch != 0:
            parts.append("{0}!".format(self._version.epoch))

        # Release segment
        parts.append(".".join(str(x) for x in self._version.release))

        return "".join(parts)

    @property
    def local(self):
        version_string = str(self)
        if "+" in version_string:
            return version_string.split("+", 1)[1]

    @property
    def is_prerelease(self):
        return bool(self._version.dev or self._version.pre)

    @property
    def is_postrelease(self):
        return bool(self._version.post)
def _parse_letter_version(letter: str, number: str) -> Tuple[str, int]:
    """
    Parse the letter version and number into a tuple.

    Args:
        letter: The letter component of the version.
        number: The numeric component of the version.

    Returns:
        A tuple containing the normalized letter version and the number converted to an integer.

    Examples:
        >>> _parse_letter_version("a", "2")
        ("a", 2)

        >>> _parse_letter_version("c", None)
        ("rc", 0)
    """

    def normalize_letter_version(letter: str) -> str:
        """
        Normalize the letter version.

        Args:
            letter: The letter component of the version.

        Returns:
            The normalized letter version.
        """
        letter = letter.lower()

        if letter == "alpha":
            return "a"
        elif letter == "beta":
            return "b"
        elif letter in ["c", "pre", "preview"]:
            return "rc"
        elif letter in ["rev", "r"]:
            return "post"
        else:
            return letter

    if letter:
        if number is None:
            number = 0

        letter = normalize_letter_version(letter)

        return letter, int(number)

    if not letter and number:
        letter = "post"
        return letter, int(number)

    return None, 0


_local_version_seperators = re.compile(r"[\._-]")


def _parse_local_version(local):
    """
    Takes a string like abc.1.twelve and turns it into ("abc", 1, "twelve").
    """
    if local is not None:
        return tuple(
            part.lower() if not part.isdigit() else int(part)
            for part in _local_version_seperators.split(local)
        )


def _cmpkey(
    epoch: int,
    release: Tuple[int],
    pre: Optional[str],
    post: Optional[str],
    dev: Optional[str],
    local: Optional[Tuple[Union[int, str]]],
) -> Tuple[
    int, Tuple[int], Tuple[int, str], Tuple[int, str], Tuple[int, str], Union[Tuple]
]:
    """Generate a comparison key for sorting versions.

    Args:
        epoch: The epoch component of the version.
        release: The release segment of the version.
        pre: The pre-release component of the version.
        post: The post-release component of the version.
        dev: The development release component of the version.
        local: The local version component of the version.

    Returns:
        The comparison key for sorting versions.
    """

    def reversed_release():
        yield from itertools.dropwhile(lambda x: x == 0, reversed(release))

    # Remove trailing zeros from the release component to create a more accurate sorting key.
    release = tuple(reversed(list(reversed_release())))

    # Set default values for the pre-release, post-release, and development release components when necessary.
    if pre is None:
        pre = Infinity if post or dev else -Infinity
    elif pre in ("-Infinity", "+Infinity"):
        pre = int(pre)
    elif "-" in pre:
        pre_parts = pre.split("-")
        pre_l = pre_parts[0]
        pre_n = int(pre_parts[1]) if len(pre_parts) == 2 else -Infinity
        pre = (pre_l, pre_n)
    else:
        pre = (pre, -Infinity)

    if post is None:
        post = -Infinity
    elif "-" in post:
        post_parts = post.split("-")
        post_l = post_parts[0]
        post_n = int(post_parts[1]) if len(post_parts) == 2 else -Infinity
        post = (post_l, post_n)
    else:
        post = (post, -Infinity)

    if dev is None:
        dev = Infinity
    elif dev == "-Infinity":
        dev = -Infinity
    elif "-" in dev:
        dev_parts = dev.split("-")
        dev_l = dev_parts[0]
        dev_n = int(dev_parts[1]) if len(dev_parts) == 2 else -Infinity
        dev = (dev_l, dev_n)
    else:
        dev = (dev, -Infinity)

    # Set default value for the local version component when necessary.
    if local is None:
        local = -Infinity
    else:
        # Parse the local version component to implement the sorting rules specified in PEP 440.
        local_parts = []
        for i in local:
            if isinstance(i, int):
                local_parts.append((i, ""))
            else:
                local_parts.append((-Infinity, i))
        local = tuple(local_parts)

    return epoch, release, pre, post, dev, local
