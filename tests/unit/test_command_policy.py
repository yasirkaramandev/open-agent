from openagent.security.command_policy import Decision, evaluate


def test_git_push_denied():
    assert evaluate("git push origin main").decision is Decision.DENY


def test_npm_publish_denied():
    assert evaluate("npm publish").decision is Decision.DENY


def test_sudo_denied():
    assert evaluate("sudo rm file").decision is Decision.DENY


def test_reading_env_denied():
    assert evaluate("cat .env").decision is Decision.DENY


def test_ssh_key_denied():
    assert evaluate("cat ~/.ssh/id_rsa").decision is Decision.DENY


def test_rm_rf_needs_approval():
    assert evaluate("rm -rf build").decision is Decision.APPROVAL


def test_network_blocked_without_permission():
    assert evaluate("pip install requests", network_allowed=False).decision is Decision.APPROVAL


def test_network_allowed_with_permission():
    assert evaluate("pip install requests", network_allowed=True).decision is Decision.ALLOW


def test_plain_command_allowed():
    assert evaluate("pytest -q").decision is Decision.ALLOW
    assert evaluate("ls -la").allowed is True


def test_empty_command_denied():
    assert evaluate("   ").decision is Decision.DENY
