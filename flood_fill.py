import sys
from typing import TYPE_CHECKING, Tuple
import wx
from amulet.api.errors import ChunkDoesNotExist

from amulet.operations.fill import fill

from amulet_map_editor.api.wx.ui.base_select import EVT_PICK
from amulet_map_editor.api.wx.ui.block_select import BlockDefine
from amulet_map_editor.programs.edit.api.operations import OperationUI
from amulet_map_editor.programs.edit.api.events import EVT_BOX_CLICK

if TYPE_CHECKING:
    from amulet.api.level import BaseLevel
    from amulet_map_editor.programs.edit.api.canvas import EditCanvas


class FloodFill(wx.Panel, OperationUI):
    def __init__(
            self,
            parent: wx.Window,
            canvas: "EditCanvas",
            world: "BaseLevel",
            options_path: str,
    ):
        wx.Panel.__init__(self, parent)
        OperationUI.__init__(self, parent, canvas, world, options_path)

        self._sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self._sizer)

        options = self._load_options({})

        self._description = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP
        )
        self._sizer.Add(self._description, 0, wx.ALL | wx.EXPAND, 5)
        self._description.SetLabel("ペイントツールのバケツのように、選択したマスを起点として空洞を指定したブロックで埋めます。")
        self._description.Fit()

        self._find_size_label = wx.StaticText(self, wx.ID_ANY, "最大空洞探査ブロック数\n" + "※0指定で制限なし")
        self._sizer.Add(self._find_size_label, 0, wx.LEFT | wx.RIGHT, 5)

        self._find_size = wx.SpinCtrl(self, style=wx.SP_ARROW_KEYS, min=0, max=2000000000, initial=0)
        default_value = options.get('find_size')
        if default_value is not None:
            self._find_size.SetValue(int(default_value))

        self._sizer.Add(self._find_size, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 5)

        self._block_define_label = wx.StaticText(self, wx.ID_ANY, "空洞を埋めるブロック")
        self._sizer.Add(self._block_define_label, 0, wx.LEFT | wx.RIGHT, 5)
        self._block_define = BlockDefine(
            self,
            world.translation_manager,
            wx.VERTICAL,
            *(options.get("fill_block_options", []) or [world.level_wrapper.platform]),
            show_pick_block=True
        )
        self._block_click_registered = False
        self._block_define.Bind(EVT_PICK, self._on_pick_block_button)
        self._sizer.Add(self._block_define, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.ALIGN_CENTRE_HORIZONTAL, 5)

        self._run_button = wx.Button(self, label="実行")
        self._run_button.Bind(wx.EVT_BUTTON, self._run_operation)
        self._sizer.Add(self._run_button, 0, wx.ALL | wx.ALIGN_CENTRE_HORIZONTAL, 5)

        self.Layout()

    @property
    def wx_add_options(self) -> Tuple[int, ...]:
        return (1,)

    def _on_pick_block_button(self, evt):
        """Set up listening for the block click"""
        if not self._block_click_registered:
            self.canvas.Bind(EVT_BOX_CLICK, self._on_pick_block)
            self._block_click_registered = True
        evt.Skip()

    def _on_pick_block(self, evt):
        self.canvas.Unbind(EVT_BOX_CLICK, handler=self._on_pick_block)
        self._block_click_registered = False
        x, y, z = self.canvas.cursor_location
        self._block_define.universal_block = (
            self.world.get_block(x, y, z, self.canvas.dimension),
            None,
        )

    def _get_fill_block(self):
        return self._block_define.universal_block[0]

    def unload(self):
        self._save_options(
            {
                "find_size": self._find_size.GetValue(),
                "fill_block": self._get_fill_block(),
                "fill_block_options": (
                    self._block_define.platform,
                    self._block_define.version_number,
                    self._block_define.force_blockstate,
                    self._block_define.namespace,
                    self._block_define.block_name,
                    self._block_define.properties,
                ),
            }
        )

    def _run_operation(self, _):
        self.canvas.run_operation(
            lambda: self._flood_fill()
        )

    def _flood_fill(self):
        # 再起回数の上限突破
        sys.setrecursionlimit(2000000000)

        dimension = self.canvas.dimension
        count = 0
        que_count = 0
        max_count = self._find_size.GetValue()
        min_x, min_y, min_z = self.canvas.selection.selection_group.min
        max_x, max_y, max_z = self.canvas.selection.selection_group.max

        # 範囲選択が1マスでない場合エラー
        if not (min_x == (max_x - 1) and min_y == (max_y - 1) and min_z == (max_z - 1)):
            wx.MessageBox("選択範囲が1マスではありません", "塗りつぶし")
            return

        queue = [(min_x, min_y, min_z)]

        while len(queue) > 0:
            x, y, z = queue.pop()
            cx, cz = x >> 4, z >> 4
            offset_x, offset_z = x - 16 * cx, z - 16 * cz
            count += 1

            try:
                chunk = self.world.get_chunk(cx, cz, dimension)
            except ChunkDoesNotExist:
                # チャンク読み込めなかったら次のループ
                continue

            # 探査ブロックが空気ブロック以外の場合次のループ
            if not (chunk.get_block(offset_x, y, offset_z).base_name == "air"
                    or chunk.get_block(offset_x, y, offset_z).base_name == "cave_air"
                    or chunk.get_block(offset_x, y, offset_z).base_name == "void_air"):
                continue

            # 探査ブロックの最大数を超えた場合終わり
            if 0 < max_count <= count:
                wx.MessageBox("探査数が最大値に到達しました\n"
                              + "検査を行った分を塗りつぶしてあります\n"
                              + "不要な場合はRedoを実行してください", "塗りつぶし")
                return

            # ブロックの設置
            chunk.set_block(offset_x, y, offset_z, self._get_fill_block())

            # チャンクのセーブフラグをTrueにする
            chunk.changed = True

            # 隣接するブロックの探査キューを追加
            queue.append((x + 1, y, z))
            queue.append((x - 1, y, z))
            if y < 255:
                queue.append((x, y + 1, z))
                que_count += 1
            if y > 0:
                queue.append((x, y - 1, z))
                que_count += 1
            queue.append((x, y, z + 1))
            queue.append((x, y, z - 1))

            que_count += 4

            yield count / que_count


export = {
    "name": "塗りつぶし",  # the name of the plugin
    "operation": FloodFill,  # the actual function to call when running the plugin
}
