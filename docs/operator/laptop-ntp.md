# Operator laptop as the LAN NTP upstream

The Pis run `chrony` and discipline their clocks against the dhcp-master
Pi (`10.10.10.1`), which in turn slews against the operator laptop
(`10.10.10.2`) when the laptop is connected. This file documents how to
set up the laptop side. The laptop config is **out-of-band** to this
repo (same model as `dhcp_config`); these instructions are the operator
contract.

## Prereq: DHCP reservation for the laptop

The dhcp-master Pi expects to find an NTP server at `10.10.10.2`. Add
a reservation in the `dhcp_config` sibling repo's `dhcpd.conf`:

```
host laptop {
  hardware ethernet AA:BB:CC:DD:EE:FF;     # the laptop's LAN MAC
  fixed-address 10.10.10.2;
}
```

Commit, deploy to the dhcp-master per that repo's procedure.

## Linux laptop (chrony)

Install chrony if missing (`sudo apt install chrony`), then add to
`/etc/chrony/chrony.conf` (or a snippet under `/etc/chrony/conf.d/`):

```
# Keep your distro's default upstream pool entries; just add this:
allow 10.10.10.0/24
```

Restart: `sudo systemctl restart chrony`.

If `ufw` is active:

```
sudo ufw allow from 10.10.10.0/24 to any port 123 proto udp
```

## macOS laptop

The built-in `timed` does not serve NTP. Install chrony via Homebrew:

```
brew install chrony
```

Drop the same `allow 10.10.10.0/24` line into chrony's config (path
depends on Homebrew prefix; `brew --prefix chrony` then look under
`etc/chrony.conf`). Start with `sudo brew services start chrony`.

If you'd rather not run a chrony server on macOS, you can skip this
and accept that if the laptop is connected but not actually serving
NTP to the LAN (for example, chrony is not installed/running or
UDP/123 is blocked), the cluster won't have a true upstream — the
dhcp-master Pi will fall back to its `local stratum 10` and the
cluster will still mutually agree, just not on true UTC.

## Verify

From any Pi on the LAN:

```
chronyc -h 10.10.10.2 tracking      # the laptop is reachable + serving
chronyc sources                     # local chrony is using its expected upstream
```

On the dhcp-master Pi, `chronyc sources` should show `10.10.10.2` with
`^*` (currently selected). On the other Pis, it should show
`10.10.10.1` with `^*`.

Compare clocks: `date` on each Pi should agree within a second or two
of the laptop.
