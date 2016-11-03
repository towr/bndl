from collections import Iterable
from configparser import ConfigParser
from functools import lru_cache
import importlib
import os
import shlex
import sys


BNDL_ENV_KEY = 'BNDL_CONF'
_NOT_SET = object()


_SETTINGS_CACHE = {}


class Config(object):
    def __init__(self, values=None, use_environment=True, **kwargs):
        if use_environment:
            self.values = {}

            # read from .bndl.ini files
            config = ConfigParser()
            config.read(['~/bndl.ini',
                         './bndl.ini',
                         '~/.bndl.ini',
                         './.bndl.ini', ])
            for section in config.sections():
                for key, value in config[section].items():
                    self.values['%s.%s' % (section, key)] = value

            # read from BNDL_CONF environment variable
            env_config = os.environ.get(BNDL_ENV_KEY, '')
            for option in shlex.split(env_config):
                option = option.split('=')
                if len(option) != 2:
                    raise RuntimeError('%s not in key=value format in BNDL_CONFIG environment variable' % option)
                self[option[0]] = option[1]

            if values:
                # override with config provided through the constructor
                self.values.update(values)
        else:
            self.values = values or {}

        if kwargs:
            self.values.update(kwargs)


    @lru_cache(1024)
    def _get_setting(self, key):
        pkg, *attr = key.rsplit('.', 1)
        if attr:
            attr = attr[0]
            mod = sys.modules.get(pkg)
            if not mod:
                try:
                    mod = importlib.import_module(pkg)
                except ImportError:
                    ...
            if mod:
                return getattr(mod, attr)

    def get(self, key, fmt=None, default=_NOT_SET):
        setting = self._get_setting(key)
        if setting:
            if fmt is None:
                fmt = setting.fmt
            if default is _NOT_SET:
                default = setting.default
        value = self.values.get(key, _NOT_SET)
        if value is _NOT_SET:
            if default is not _NOT_SET:
                return default
            else:
                return None
        else:
            return fmt(value) if fmt else value

    def get_int(self, *args, **kwargs):
        return self.get(*args, fmt=int, **kwargs)

    def get_float(self, *args, **kwargs):
        return self.get(*args, fmt=float, **kwargs)

    def get_bool(self, *args, **kwargs):
        return self.get(*args, fmt=bool, **kwargs)

    def get_str(self, *args, **kwargs):
        return self.get(*args, fmt=str, **kwargs)

    def get_attr(self, *args, obj, **kwargs):
        attr = self.get(*args, fmt=str, **kwargs)
        return getattr(obj, attr)

    def __setitem__(self, key, value):
        self.values[key] = value
        return self

    def __getitem__(self, key):
        return self.get(key)

    def __repr__(self):
        return '<Conf %r>' % self.values

    def __reduce__(self):
        return Config, (self.values,)


class Setting(object):
    default = None
    fmt = None
    desc = None

    def __init__(self, default=_NOT_SET, fmt=None, desc=None):
        self.default = default
        self.desc = desc
        if fmt is not None:
            assert callable(fmt)
            self.fmt = fmt


class String(Setting):
    pass


class Bool(Setting):
    def fmt(self, v):
        if type(v) is bool:
            return v
        else:
            return str(v).lower() in ('1', 'true', 'yes')


class Int(Setting):
    fmt = int


class Float(Setting):
    fmt = float


class CSV(String):
    def fmt(self, v):
        if isinstance(v, Iterable) and not isinstance(v, str):
            return v
        return list(e.strip() for e in v.split(','))


class Attr(Setting):
    def __init__(self, *args, obj=None, **kwargs):
        assert obj is not None
        super().__init__(*args, **kwargs)
        self.obj = obj

    def fmt(self, v):
        return getattr(self.obj, str(v), self.default)


class Enum(Setting):
    def __init__(self, *args, choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.choices = choices

    def fmt(self, v):
        if v in self.choices:
            return v
        else:
            raise ValueError('Unsupported value %s (must be one of %r)' % (v, self.choices))
