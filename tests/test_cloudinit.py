import yaml

from capsule.cloudinit import user_data
from capsule.config import resolve


def test_cloud_init_has_user_gid_and_packages(cfg):
    cfg("defaults:\n  user: dev:1500:1600\n  packages: [btop]\n")
    data = user_data(resolve("a"))
    assert data.startswith("#cloud-config")
    doc = yaml.safe_load(data)
    assert doc["users"][0]["uid"] == 1500
    assert "groupadd -g 1600 dev" in doc["bootcmd"][0]
    assert "btop" in doc["packages"]
    assert "docker.io" in doc["packages"]


def test_mount_parents_are_created_owned_by_the_user(cfg, tmp_path):
    cfg(f"defaults:\n  user: dev:1000:1000\n  mounts: ['{tmp_path}:/home/dev/a/b/c']\n")
    runcmd = yaml.safe_load(user_data(resolve("a")))["runcmd"]
    assert "install -d -o dev -g dev /home/dev/a" in runcmd
    assert "install -d -o dev -g dev /home/dev/a/b" in runcmd
    assert not any(command.endswith("/home/dev/a/b/c") for command in runcmd)  # the mount point itself is left to Incus


def test_tools_come_from_mise_not_curl_installers(cfg):
    runcmd = yaml.safe_load(user_data(resolve("a")))["runcmd"]
    assert not any("herdr.dev" in command for command in runcmd)
