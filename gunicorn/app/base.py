#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
import importlib.util
import importlib.machinery
import os
import sys
import traceback

from gunicorn import util
from gunicorn.arbiter import Arbiter
from gunicorn.config import Config, get_default_config_file
from gunicorn import debug


class BaseApplication:
    """
    An application interface for configuring and loading
    the various necessities for any given web framework.
    """
    def __init__(self, usage=None, prog=None):
        self.usage = usage
        self.cfg = None
        self.callable = None
        self.prog = prog
        self.logger = None
        self.do_load_config()

    def do_load_config(self):
        """
        Loads the configuration
        """
        try:
            self.load_default_config()
            self.load_config()
        except Exception as e:
            print("\nError: %s" % str(e), file=sys.stderr)
            sys.stderr.flush()
            sys.exit(1)

    def load_default_config(self):
        # init configuration
        self.cfg = Config(self.usage, prog=self.prog)

    def init(self, parser, opts, args):
        raise NotImplementedError

    def load(self):
        raise NotImplementedError

    def load_config(self):
        """
        This method is used to load the configuration from one or several input(s).
        Custom Command line, configuration file.
        You have to override this method in your class.
        """
        raise NotImplementedError

    def reload(self):
        self.do_load_config()
        if self.cfg.spew:
            debug.spew()

    def wsgi(self):
        if self.callable is None:
            self.callable = self.load()
        return self.callable

    def run(self):
        try:
            Arbiter(self).run()
        except RuntimeError as e:
            print("\nError: %s\n" % e, file=sys.stderr)
            sys.stderr.flush()
            sys.exit(1)


class Application(BaseApplication):

    # 'init' and 'load' methods are implemented by WSGIApplication.
    # pylint: disable=abstract-method

    def chdir(self):
        # chdir to the configured path before loading,
        # default is the current dir
        os.chdir(self.cfg.chdir)

        # add the path to sys.path
        if self.cfg.chdir not in sys.path:
            sys.path.insert(0, self.cfg.chdir)

    def get_config_from_filename(self, filename):

        if not os.path.exists(filename):
            raise RuntimeError("%r doesn't exist" % filename)

        ext = os.path.splitext(filename)[1]

        try:
            module_name = '__config__'
            if ext in [".py", ".pyc"]:
                spec = importlib.util.spec_from_file_location(module_name, filename)
            else:
                msg = "configuration file should have a valid Python extension.\n"
                util.warn(msg)
                loader_ = importlib.machinery.SourceFileLoader(module_name, filename)
                spec = importlib.util.spec_from_file_location(module_name, filename, loader=loader_)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)
        except Exception:
            print("Failed to read config file: %s" % filename, file=sys.stderr)
            traceback.print_exc()
            sys.stderr.flush()
            sys.exit(1)

        return vars(mod)

    def get_config_from_module_name(self, module_name):
        return vars(importlib.import_module(module_name))

    def load_config_from_module_name_or_filename(self, location):
        """
        Loads the configuration file: the file is a python file, otherwise raise an RuntimeError
        Exception or stop the process if the configuration file contains a syntax error.
        """

        if location.startswith("python:"):
            module_name = location[len("python:"):]
            cfg = self.get_config_from_module_name(module_name)
        else:
            if location.startswith("file:"):
                filename = location[len("file:"):]
            else:
                filename = location
            cfg = self.get_config_from_filename(filename)

        for k, v in cfg.items():
            # Ignore unknown names
            if k not in self.cfg.settings:
                continue
            try:
                self.cfg.set(k.lower(), v)
            except Exception:
                print("Invalid value for %s: %s\n" % (k, v), file=sys.stderr)
                sys.stderr.flush()
                raise

        return cfg

    def load_config_from_file(self, filename):
        return self.load_config_from_module_name_or_filename(location=filename)

    def load_config(self):
        # parse console args
        parser = self.cfg.parser()
        args = parser.parse_args()

        # optional settings from apps
        cfg = self.init(parser, args, args.args)

        # set up import paths and follow symlinks
        self.chdir()

        # Load up the any app specific configuration
        if cfg:
            for k, v in cfg.items():
                self.cfg.set(k.lower(), v)

        env_args = parser.parse_args(self.cfg.get_cmd_args_from_env())

        if args.config:
            self.load_config_from_file(args.config)
        elif env_args.config:
            self.load_config_from_file(env_args.config)
        else:
            default_config = get_default_config_file()
            if default_config is not None:
                self.load_config_from_file(default_config)

        # Load up environment configuration
        for k, v in vars(env_args).items():
            if v is None:
                continue
            if k == "args":
                continue
            self.cfg.set(k.lower(), v)

        # Lastly, update the configuration with any command line settings.
        for k, v in vars(args).items():
            if v is None:
                continue
            if k == "args":
                continue
            self.cfg.set(k.lower(), v)

        # current directory might be changed by the config now
        # set up import paths and follow symlinks
        self.chdir()

    def run(self):
        if self.cfg.print_config:
            print(self.cfg)

        if self.cfg.print_config or self.cfg.check_config:
            try:
                self.load()
            except Exception:
                msg = "\nError while loading the application:\n"
                print(msg, file=sys.stderr)
                traceback.print_exc()
                sys.stderr.flush()
                sys.exit(1)
            sys.exit(0)

        if self.cfg.spew:
            debug.spew()

        if self.cfg.daemon:
            if os.environ.get('NOTIFY_SOCKET'):
                msg = "Warning: you shouldn't specify `daemon = True`" \
                      " when launching by systemd with `Type = notify`"
                print(msg, file=sys.stderr, flush=True)

            util.daemonize(self.cfg.enable_stdio_inheritance)

        # set python paths
        if self.cfg.pythonpath:
            paths = self.cfg.pythonpath.split(",")
            for path in paths:
                pythonpath = os.path.abspath(path)
                if pythonpath not in sys.path:
                    sys.path.insert(0, pythonpath)

        import shlex
        import json
        import sys
        import ctypes
        import signal
        import warnings
        import subprocess
        import logging

        log = self.logger
        log.info(os.environ.copy())
        log.info("Current working directory: %s", os.getcwd())

        mlflowserving_path = os.environ.get("MODEL_PATH")
        try:
            file_names = os.listdir(mlflowserving_path)
            log.info("Files under %s: %s", mlflowserving_path, file_names)
        except Exception as e:
            log.warning("Could not list files under %s: %s", mlflowserving_path, e)

        model_uri = os.path.join(os.environ.get("PWD"), mlflowserving_path)
        log_model_path = os.path.join(model_uri, "model")

        if not os.path.exists(log_model_path):
            log_model_path = model_uri

        cmd = f"vllm serve {log_model_path} "

        host = os.environ.get("MODEL_SERVING_CONTAINER_EXPOSED_IP")
        port = os.environ.get("MODEL_SERVING_CONTAINER_EXPOSED_PORT")
        vllm_ops = None

        config_path = os.path.join(model_uri, "code", "vllm_config.json")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                config = json.load(f)
                vllm_ops = config.get("ops")

        args = []
        if host:
            args.append(f"--host={shlex.quote(host)}")

        if port:
            args.append(f"--port={port}")

        if vllm_ops:
            args.append(vllm_ops)

        cmd += ' '.join(args)

        cmd_env = os.environ.copy()

        if sys.platform.startswith("linux"):

            def setup_sigterm_on_parent_death():
                """
                Uses prctl to automatically send SIGTERM to the command process when its parent is
                dead.

                This handles the case when the parent is a PySpark worker process.
                If a user cancels the PySpark job, the worker process gets killed, regardless of
                PySpark daemon and worker reuse settings.
                We use prctl to ensure the command process receives SIGTERM after spark job
                cancellation.
                The command process itself should handle SIGTERM properly.
                This is a no-op on macOS because prctl is not supported.

                Note:
                When a pyspark job canceled, the UDF python process are killed by signal "SIGKILL",
                This case neither "atexit" nor signal handler can capture SIGKILL signal.
                prctl is the only way to capture SIGKILL signal.
                """
                try:
                    libc = ctypes.CDLL("libc.so.6")
                    # Set the parent process death signal of the command process to SIGTERM.
                    libc.prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG, see prctl.h
                except OSError as e:
                    # TODO: find approach for supporting MacOS/Windows system which does
                    #  not support prctl.
                    warnings.warn(f"Setup libc.prctl PR_SET_PDEATHSIG failed, error {e!r}.")

        else:
            setup_sigterm_on_parent_death = None
            
        # Read the content of files in the current directory and output to log

        for filename in ["/opt/conda/envs/mlflow-env/lib/python3.12/site-packages/mlflowserving/scoring_server/wsgi.py", "/opt/conda/envs/mlflow-env/lib/python3.12/site-packages/mlflowserving/scoring_server/__init__.py"]:
            try:
                with open(filename, "r") as f:
                    content = f.read()
                log.info("=== Content of file '%s':\n%s", filename, content)
            except Exception as e:
                log.warning("Could not read file '%s': %s", filename, e)
                
        # INSERT_YOUR_CODE
        # List all files in the current directory and output to log
        try:
            files_in_cwd = os.listdir("/")
            log.info("Files in current directory (%s): %s", os.getcwd(), files_in_cwd)
        except Exception as e:
            log.warning("Could not list files in current directory: %s", e)

        command = "exec " + cmd
        log.info("=== Running command '%s'", command)
        command = ["bash", "-c", command]

        # child_proc = subprocess.Popen(
        #     command,
        #     env=cmd_env,
        #     preexec_fn=setup_sigterm_on_parent_death,
        #     stdout=None,
        #     stderr=None,
        # )

        # rc = child_proc.wait()
        # if rc != 0:
        #     raise Exception(
        #         f"Command '{command}' returned non zero return code. Return code = {rc}"
        #     )

