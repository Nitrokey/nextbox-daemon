from pathlib import Path
import urllib
import ssl 
import requests

from nextbox_daemon.config import log, cfg
from nextbox_daemon.command_runner import CommandRunner
from nextbox_daemon.dns_manager import DNSManager

class NextcloudError(Exception):
    pass


class Nextcloud:
    """Nextcloud administration, wrapping nextcloud's `occ` cli-tool"""

    occ_cmd = ("docker", "exec", "-u", "www-data", 
        "nextbox-compose_app_1", "/var/www/html/occ", "-n", "--ansi",
        "--no-warnings")

    config_value_keys = ["overwritehost", "overwriteprotocol", "overwritewebroot", "overwritecondaddr"]
    config_list_keys = ["trusted_domains", "trusted_proxies"]

    can_install_path = "/srv/nextcloud/config/CAN_INSTALL"
    config_path = "/srv/nextcloud/config/config.php"

    @property
    def is_installed(self):
        """If `can_install_path` exists, nextcloud's initialization is not done"""
        return not Path(self.can_install_path).exists()

    @property
    def is_maintenance(self):
        cpath = Path(self.config_path)
        if not cpath.exists():
            return False

        with cpath.open() as fd:
            for line in fd:
                if "maintenance" in line:
                    return "true" in line

    def check_reachability(self):
        # try:
        #     content = urllib.request.urlopen(url).read().decode("utf-8")   
        # except urllib.error.URLError:
        #     return False, "url-error"         
        # except ssl.CertificateError:
        #     # this very likely is due to a bad certificate
        #     return False, "cert"
        # except Exception:
        #     return False, "unknown"

        # if "Nextcloud" in content:
        #     return True, None

        # return False, "not-nextcloud"

        dns = DNSManager()

        data_dct = {
            "ipv4": dns.get_ipv4() or "",
            "ipv6": dns.get_ipv6() or "",
            "domain": cfg["config"]["domain"] or "",
            "token": cfg["config"]["nk_token"]
        }

        res = requests.post("https://nextbox.link/reachable", json=data_dct)
        return res, data_dct

    def run_cmd(self, *args):
        """
        Run `occ` command with given `args`

        * raise `NextcloudError` on error
        * return (merged stdin + stderr) output on success
        """
        cr = CommandRunner(self.occ_cmd + args, block=True)
        if cr.returncode != 0:
            cr.log_output()
            raise NextcloudError("failed to execute nextcloud:occ command")
        
        return cr.output[:-2]

    def get_version(self):
        """Return current nextcloud version-tuple"""
        output = self.run_cmd("status")
        for line in output:
            if "- version:" in line:
                return line.split(":")[-1].strip().split(".")
        return False

    def get_config(self, key):
        """Return config value identified by `key`"""
        return self.run_cmd("config:system:get", key)

    def set_config(self, key, data, idx=None):
        """
        Set config value identified by `key` to `data`.

        * determining the type is based on `key` in any of `config_{list,value}_keys`.
        * `idx: int` may be passed to set just one item of a list/array config
        * `data: [list, str]` strictly based on `key`
        """
        # set config list
        if key in self.config_list_keys:
            # single item in config list (data as item at `idx` in list)
            if idx is not None:
                self.run_cmd("config:system:set", key, str(idx), "--value", data)
                return

            # all items in data (as list)
            for idx, item in enumerate(data):
                self.run_cmd("config:system:set", key, str(idx), "--value", item)

        # set config string
        elif key in self.config_value_keys:
            self.run_cmd("config:system:set", key, "--type", "string", "--value", data)

        else:
            raise NextcloudError(f"unknown key: {key}")

    def delete_config(self, key):
        """Deleting config key-value pair completly"""
        self.run_cmd("config:system:delete", key)

    def set_maintenance_on(self):
        """Activating nextcloud maintainance mode"""
        return self.run_cmd("maintenance:mode", "--on")

    def set_maintenance_off(self):
        """Deactivating nextcloud maintainance mode"""
        return self.run_cmd("maintenance:mode", "--off")
    

    def soft_reset(self):
        """A soft reset is switching off maintainance and disabling all apps"""

        ret = self.set_maintenance_off()
        ret &= self.run_cmd("app:disable", "mail")

        return ret


    def enable_nextbox_app(self):
        """Enable nextbox-app for this nextcloud"""
        out = self.run_cmd("app:enable", "nextbox")
        out = " ".join(out)
        return "already" in out

