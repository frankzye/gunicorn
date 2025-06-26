#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import os

from gunicorn.errors import ConfigError
from gunicorn.app.base import Application
from gunicorn import util


class WSGIApplication(Application):
    def init(self, parser, opts, args):
        self.app_uri = None

        if opts.paste:
            from .pasterapp import has_logging_config

            config_uri = os.path.abspath(opts.paste)
            config_file = config_uri.split('#')[0]

            if not os.path.exists(config_file):
                raise ConfigError("%r not found" % config_file)

            self.cfg.set("default_proc_name", config_file)
            self.app_uri = config_uri

            if has_logging_config(config_file):
                self.cfg.set("logconfig", config_file)

            return

        if len(args) > 0:
            self.cfg.set("default_proc_name", args[0])
            self.app_uri = args[0]

    def load_config(self):
        super().load_config()

        if self.app_uri is None:
            if self.cfg.wsgi_app is not None:
                self.app_uri = self.cfg.wsgi_app
            else:
                raise ConfigError("No application module specified.")

    def load_wsgiapp(self):
        return util.import_app(self.app_uri)

    def load_pasteapp(self):
        from .pasterapp import get_wsgi_app
        return get_wsgi_app(self.app_uri, defaults=self.cfg.paste_global_conf)

    def load(self):
        if self.cfg.paste is not None:
            return self.load_pasteapp()
        else:
            return self.load_wsgiapp()


def run(prog=None):
    """\
    The ``gunicorn`` command line runner for launching Gunicorn with
    generic WSGI applications.
    """
    from gunicorn.app.wsgiapp import WSGIApplication
    WSGIApplication("%(prog)s [OPTIONS] [APP_MODULE]", prog=prog).run()


if __name__ == '__main__':
    import logging
    import shlex
    import json
    import sys
    import ctypes
    import signal
    import warnings
    import subprocess

    log = logging.getLogger(__name__)
    log.info(os.environ.copy())
    log.info("Current working directory: %s", os.getcwd())

    mlflowserving_path = os.environ.get("MODEL_PATH")
    try:
        file_names = os.listdir(mlflowserving_path)
        log.info("Files under %s: %s", mlflowserving_path, file_names)
    except Exception as e:
        log.warning("Could not list files under %s: %s", mlflowserving_path, e)

    model_uri = os.path.join(os.environ.get("PWD"), os.environ.get("PWD"))
    log_model_path = os.path.join(model_uri, "model")

    if not os.path.exists(log_model_path):
        log_model_path = model_uri

    cmd = f"vllm serve {log_model_path} "

    host = os.environ.get("MODEL_SERVING_CONTAINER_EXPOSED_IP")
    port = os.environ.get("MODEL_SERVING_CONTAINER_EXPOSED_PORT")

    config_path = os.path.join(model_uri, "code", "vllm_config.json")
    if os.path.exists(config_path):
        with open(os.path.join(model_uri, "code", "vllm_config.json"), "r") as f:
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

    command = "exec " + cmd
    log.info("=== Running command '%s'", command)
    command = ["bash", "-c", command]

    child_proc = subprocess.Popen(
        command,
        env=cmd_env,
        preexec_fn=setup_sigterm_on_parent_death,
        stdout=None,
        stderr=None,
    )

    rc = child_proc.wait()
    if rc != 0:
        raise Exception(
            f"Command '{command}' returned non zero return code. Return code = {rc}"
        )
