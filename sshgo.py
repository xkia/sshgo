#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys
import curses
import locale
import math
import re
import linecache
from optparse import OptionParser

locale.setlocale(locale.LC_ALL, "")

script = sys.path[0] + "/login.sh"
script_nest = sys.path[0] + "/login_nest.sh"
sshHosts = sys.path[0] + "/hosts"
ipv4_two_nodes_pattern = r'\b(?:[0-9]{1,3}\.){1,2}[0-9]{1,3}\b'

def _assert(exp, err):
    if not exp:
        print(err, file=sys.stderr)
        sys.exit(1)


def _dedup(ls):
    return sorted(set(ls))


def _get_known_hosts():
    fn = os.path.expanduser(sshHosts)
    hosts = []
    if not os.path.exists(fn):
        return hosts

    with open(fn, "r") as fp:
        for line in fp:
            parts = line.strip().split(" ")
            if not parts:
                continue
            host = parts[0]
            if "," in host:
                host = host.split(",", 1)[0]
            if host:
                hosts.append(host)
    return _dedup(hosts)


def _get_host_name(line_con, node_host):
    _, sep, comment = line_con.partition("# ")
    node_name = comment if sep else node_host
    if node_host != node_name:
        node_name = node_host + " (" + node_name.strip() + ")"
    return node_name


class SSHGO:
    UP = -1
    DOWN = 1

    KEY_O = 79
    KEY_R = 82
    KEY_G = 71
    KEY_o = 111
    KEY_r = 114
    KEY_g = 103
    KEY_c = 99
    KEY_C = 67
    KEY_m = 109
    KEY_M = 77
    KEY_d = 0x64
    KEY_u = 0x75
    KEY_SPACE = 32
    KEY_ENTER = 10
    KEY_q = 113
    KEY_ESC = 27

    KEY_j = 106
    KEY_k = 107

    KEY_SPLASH = 47

    screen = None

    def _parse_tree_from_config_file(self, config_file):
        tree = {"line_number": None, "expanded": True, "line": None, "sub_lines": []}

        def find_parent_line(new_node):
            line_number = new_node["line_number"]
            level = new_node["level"]

            if level == 0:
                return tree

            stack = tree["sub_lines"] + []
            parent = None
            while len(stack):
                node = stack.pop()
                if node["line_number"] < line_number and node["level"] == level - 1:
                    if parent is None:
                        parent = node
                    elif node["line_number"] > parent["line_number"]:
                        parent = node
                if len(node["sub_lines"]) and node["level"] < level:
                    stack = stack + node["sub_lines"]
                    continue

            return parent

        tree_level = None
        nodes_pool = []
        line_number = 0

        for line in open(config_file, "r"):
            line_number += 1
            line_con = line.strip()
            if line_con == "" or line_con[0] == "#":
                continue
            expand = True
            if line_con[0] == "-":
                line_con = line_con[1:]
                expand = False
            indent = re.findall(r"^[\t ]*(?=[^\t ])", line)[0]
            line_level = indent.count("    ") + indent.count("\t")
            if tree_level == None:
                _assert(line_level == 0, "invalid indent,line:" + str(line_number))
            else:
                _assert(
                    line_level <= tree_level or line_level == tree_level + 1,
                    "invalid indent,line:" + str(line_number),
                )
            tree_level = line_level
            node_infos = re.split(r"\s+", line_con.strip())
            node_host = node_infos[0] if len(node_infos) >= 2 else line_con
            node_user = node_infos[1] if len(node_infos) >= 2 else ""
            node_pass = node_infos[2] if len(node_infos) >= 3 else ""
            node_id_file = node_infos[3] if len(node_infos) == 4 else ""
            node_name = _get_host_name(line_con, node_host)
            # line 对象用于显示名称
            new_node = {
                "nest_parent": None,
                "level": tree_level,
                "expanded": expand,
                "line_number": line_number,
                "line": node_name,
                "user": node_user,
                "password": node_pass,
                "id_file": node_id_file,
                "host": node_host,
                "sub_lines": [],
            }
            nodes_pool.append(new_node)
            parent = find_parent_line(new_node)

            # add the nest_parent to node
            if parent.get("level"):
                nest_parent_node = find_parent_line(parent)
                if nest_parent_node and len(nest_parent_node["sub_lines"]) > 0:
                    new_node["nest_parent"] = nest_parent_node["sub_lines"][0]

            parent["sub_lines"].append(new_node)

        return tree, nodes_pool

    def __init__(self, config_file):
        self.hosts_tree, self.hosts_pool = self._parse_tree_from_config_file(
            config_file
        )

        known_host_list = _get_known_hosts()
        MAGIC_LINE_NUMBER = 666
        known_hosts = {
            "sub_lines": [],
            "line_number": MAGIC_LINE_NUMBER,
            "line": "known hosts",
            "expanded": False,
            "level": 0,
        }
        for host in known_host_list:
            known_hosts["sub_lines"].append(
                {
                    "sub_lines": [],
                    "line_number": MAGIC_LINE_NUMBER,
                    "line": host,
                    "expanded": True,
                    "level": 1,
                }
            )

        self.hosts_tree["sub_lines"].append(known_hosts)
        self.hosts_pool.append(known_hosts)

        self.screen = curses.initscr()
        curses.noecho()
        curses.cbreak()
        curses.curs_set(0)
        self.screen.keypad(1)
        self.screen.border(0)

        self.top_line_number = 0
        self.highlight_line_number = 0
        self.search_keyword = None

        curses.start_color()
        curses.use_default_colors()

        # highlight
        curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLUE)
        self.COLOR_HIGHLIGHT = 2
        # red
        curses.init_pair(3, curses.COLOR_RED, -1)
        self.COLOR_RED = 3

        # red highlight
        curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLUE)
        self.COLOR_RED_HIGH = 4

        # white bg
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_WHITE)
        self.COLOR_WBG = 5

        # black bg
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_BLACK)
        self.COLOR_BBG = 6

        self.run()

    def run(self):
        while True:
            self.render_screen()
            c = self.screen.getch()
            if c == curses.KEY_UP or c == self.KEY_k:
                self.updown(-1)
            elif c == curses.KEY_DOWN or c == self.KEY_j:
                self.updown(1)
            elif c == self.KEY_u:
                for i in range(0, curses.tigetnum("lines")):
                    self.updown(-1)
            elif c == self.KEY_d:
                for i in range(0, curses.tigetnum("lines")):
                    self.updown(1)
            elif c == self.KEY_ENTER or c == self.KEY_SPACE:
                self.toggle_node()
            elif c == self.KEY_ESC or c == self.KEY_q:
                self.exit()
            elif c == self.KEY_O or c == self.KEY_M:
                self.open_all()
            elif c == self.KEY_o or c == self.KEY_m:
                self.open_node()
            elif c == self.KEY_C or c == self.KEY_R:
                self.close_all()
            elif c == self.KEY_c or c == self.KEY_r:
                self.close_node()
            elif c == self.KEY_g:
                self.page_top()
            elif c == self.KEY_G:
                self.page_bottom()
            elif c == self.KEY_SPLASH:
                self.enter_search_mode()

    def exit(self):
        if self.search_keyword is not None:
            self.search_keyword = None
        else:
            sys.exit(0)

    def enter_search_mode(self):
        screen_cols = curses.tigetnum("cols")
        self.screen.addstr(0, 0, "/" + " " * screen_cols)
        curses.echo()
        curses.curs_set(1)
        self.search_keyword = self.screen.getstr(0, 1)
        curses.noecho()
        curses.curs_set(0)

    def _get_visible_lines_for_render(self):
        lines = []
        stack = self.hosts_tree["sub_lines"] + []
        while len(stack):
            node = stack.pop()
            lines.append(node)
            if node["expanded"] and len(node["sub_lines"]):
                stack = stack + node["sub_lines"]

        lines.sort(key=lambda n: n["line_number"], reverse=False)
        return lines

    def _search_node(self):
        rt = []
        try:
            kre = re.compile(self.search_keyword, re.I)
        except:
            return rt
        for node in self.hosts_pool:
            if len(node["sub_lines"]) == 0 and kre.search(node["line"]) is not None:
                rt.append(node)
        return rt

    def get_lines(self):
        if self.search_keyword is not None:
            return self._search_node()
        else:
            return self._get_visible_lines_for_render()

    def page_top(self):
        self.top_line_number = 0
        self.highlight_line_number = 0

    def page_bottom(self):
        screen_lines = curses.tigetnum("lines")
        visible_hosts = self.get_lines()
        self.top_line_number = max(len(visible_hosts) - screen_lines, 0)
        self.highlight_line_number = min(screen_lines, len(visible_hosts)) - 1

    def open_node(self):
        visible_hosts = self.get_lines()
        linenum = self.top_line_number + self.highlight_line_number
        node = visible_hosts[linenum]
        if not len(node["sub_lines"]):
            return
        stack = [node]
        while len(stack):
            node = stack.pop()
            node["expanded"] = True
            if len(node["sub_lines"]):
                stack = stack + node["sub_lines"]

    def close_node(self):
        visible_hosts = self.get_lines()
        linenum = self.top_line_number + self.highlight_line_number
        node = visible_hosts[linenum]
        if not len(node["sub_lines"]):
            return
        stack = [node]
        while len(stack):
            node = stack.pop()
            node["expanded"] = False
            if len(node["sub_lines"]):
                stack = stack + node["sub_lines"]

    def open_all(self):
        for node in self.hosts_pool:
            if len(node["sub_lines"]):
                node["expanded"] = True

    def close_all(self):
        for node in self.hosts_pool:
            if len(node["sub_lines"]):
                node["expanded"] = False

    def toggle_node(self):
        visible_hosts = self.get_lines()
        linenum = self.top_line_number + self.highlight_line_number
        node = visible_hosts[linenum]
        if len(node["sub_lines"]):
            node["expanded"] = not node["expanded"]
        else:
            self.restore_screen()

            # ssh = 'ssh'
            # if os.popen('which zssh 2> /dev/null').read().strip() != '':
            #    ssh = 'zssh'

            # run script instead of 'ssh'
            nest_parent = node["nest_parent"]
            ssh = script
            if nest_parent:
                ssh = script_nest

            host_info = re.split(":", node["host"].strip())

            port = "22"
            host = ""

            if len(host_info) == 2:
                host = host_info[0]
                port = host_info[1]
            else:
                host = host_info[0]

            if nest_parent:
                nest_host_info = re.split(":", nest_parent["host"].strip())

                nest_port = "22"
                nest_host = ""

                if len(nest_host_info) == 2:
                    nest_host = nest_host_info[0]
                    nest_port = nest_host_info[1]
                else:
                    nest_host = nest_host_info[0]

                exe_args = [
                    ssh,
                    nest_host,
                    nest_port,
                    nest_parent["user"],
                    nest_parent["password"],
                    nest_parent["id_file"],
                    host,
                    port,
                    node["user"],
                    node["password"],
                ]
            else:
                exe_args = [
                    ssh,
                    host,
                    port,
                    node["user"],
                    node["password"],
                    node["id_file"],
                ]
            os.execvp(ssh, exe_args)

    def render_screen(self):
        # clear screen
        self.screen.clear()

        # now paint the rows
        screen_lines = curses.tigetnum("lines")
        screen_cols = curses.tigetnum("cols")

        if self.highlight_line_number >= screen_lines:
            self.highlight_line_number = screen_lines - 1

        all_nodes = self.get_lines()
        if self.top_line_number >= len(all_nodes):
            self.top_line_number = 0

        top = self.top_line_number
        bottom = self.top_line_number + screen_lines
        nodes = all_nodes[top:bottom]

        if not len(nodes):
            self.screen.refresh()
            return

        if self.highlight_line_number >= len(nodes):
            self.highlight_line_number = len(nodes) - 1

        if self.top_line_number >= len(all_nodes):
            self.top_line_number = 0

        for (
            index,
            node,
        ) in enumerate(nodes):
            # linenum = self.top_line_number + index

            line = node["line"]
            if len(node["sub_lines"]):
                line += "(%d)" % len(node["sub_lines"])

            prefix = ""
            if self.search_keyword is None:
                prefix += "  " * node["level"]
            if len(node["sub_lines"]):
                if node["expanded"]:
                    prefix += "-"
                else:
                    prefix += "+"
            else:
                prefix += "o"
            prefix += " "

            # highlight current line
            if index != self.highlight_line_number:
                self.screen.addstr(index, 0, prefix, curses.color_pair(self.COLOR_RED))
                self.screen.addstr(index, len(prefix), line)
            else:
                self.screen.addstr(
                    index, 0, prefix, curses.color_pair(self.COLOR_RED_HIGH)
                )
                self.screen.addstr(
                    index, len(prefix), line, curses.color_pair(self.COLOR_HIGHLIGHT)
                )
        # render scroll bar
        for i in range(screen_lines):
            self.screen.addstr(
                i, screen_cols - 2, "|", curses.color_pair(self.COLOR_WBG)
            )

        scroll_top = int(
            math.ceil(
                (self.top_line_number + 1.0)
                / max(len(all_nodes), screen_lines)
                * screen_lines
                - 1
            )
        )
        scroll_height = int(
            math.ceil((len(nodes) + 0.0) / len(all_nodes) * screen_lines)
        )
        highlight_pos = int(
            math.ceil(
                scroll_height
                * ((self.highlight_line_number + 1.0) / min(screen_lines, len(nodes)))
            )
        )

        self.screen.addstr(
            scroll_top, screen_cols - 2, "^", curses.color_pair(self.COLOR_WBG)
        )
        self.screen.addstr(
            min(screen_lines, scroll_top + scroll_height) - 1,
            screen_cols - 2,
            "v",
            curses.color_pair(self.COLOR_WBG),
        )
        self.screen.addstr(
            min(screen_lines, scroll_top + highlight_pos) - 1,
            screen_cols - 2,
            "+",
            curses.color_pair(self.COLOR_WBG),
        )

        self.screen.refresh()

    # move highlight up/down one line
    def updown(self, increment):
        visible_hosts = self.get_lines()
        visible_lines_count = len(visible_hosts)
        next_line_number = self.highlight_line_number + increment

        # paging
        if (
            increment < 0
            and self.highlight_line_number == 0
            and self.top_line_number != 0
        ):
            self.top_line_number += self.UP
            return
        elif (
            increment > 0
            and next_line_number == curses.tigetnum("lines")
            and (self.top_line_number + curses.tigetnum("lines")) != visible_lines_count
        ):
            self.top_line_number += self.DOWN
            return

        # scroll highlight line
        if increment < 0 and (
            self.top_line_number != 0 or self.highlight_line_number != 0
        ):
            self.highlight_line_number = next_line_number
        elif (
            increment > 0
            and (self.top_line_number + self.highlight_line_number + 1)
            != visible_lines_count
            and self.highlight_line_number != curses.tigetnum("lines")
        ):
            self.highlight_line_number = next_line_number

    def restore_screen(self):
        curses.initscr()
        curses.nocbreak()
        curses.echo()
        curses.endwin()

    # catch any weird termination situations
    def __del__(self):
        self.restore_screen()


def login_main_host(host_file, sarg):
    # 解析文件,获取第二行相关配置, 默认第二行为默认配置
    # TODO 优化node info获取节点的名称,目前含义有些模糊
    default_conf_line = linecache.getline(host_file, 2)
    default_node_infos = re.split(r"\s+", default_conf_line.strip())
    default_node_host = (
        default_node_infos[0] if len(default_node_infos) >= 2 else default_conf_line
    )
    default_node_user = default_node_infos[1] if len(default_node_infos) >= 2 else ""
    default_node_pass = default_node_infos[2] if len(default_node_infos) >= 3 else ""
    default_node_id_file = default_node_infos[3] if len(default_node_infos) == 4 else ""
    default_host_info = re.split(":", default_node_host.strip())
    host = default_host_info[0]
    port = default_host_info[1] if len(default_host_info) == 2 else "22"
    ssh = script
    exe_args = [
        ssh,
        host,
        port,
        default_node_user,
        default_node_pass,
        default_node_id_file,
        sarg,
    ]
    os.execvp(ssh, exe_args)


if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option(
        "-c", "--config", help="use specified config file instead of hosts"
    )
    options, args = parser.parse_args(sys.argv)
    host_file = os.path.expanduser(sshHosts)

    if options.config is not None:
        host_file = options.config
    if not os.path.exists(host_file):
        print("hosts is not found, create it", file=sys.stderr)
        with open(host_file, "w"):
            pass
    if len(args) > 1:
        sarg = args[1]
        if re.findall(ipv4_two_nodes_pattern, str(sarg)) is not None:
            # 如果匹配到输入的是ip格式(包含完整或者一部分的ipv4, 即 xxx.xxx)
            login_main_host(host_file, sarg)
        else:
            sshgo = SSHGO(host_file)
    else:
        sshgo = SSHGO(host_file)
