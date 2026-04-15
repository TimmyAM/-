import pygame
import sys
import json
import os
import random
from PIL import Image
import itertools

# ===================== 修复核心：获取程序自身所在目录 =====================
BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
MATERIALS_FOLDER = os.path.join(BASE_DIR, "materials")

# ===================== 基础配置 =====================
pygame.init()
pygame.key.stop_text_input()
pygame.mixer.quit()

WINDOW_SIZE = (1280, 800)
UI_WIDTH = 300
CANVAS_BG_COLOR = (240, 240, 240)
WINDOW_BG_COLOR = (255, 255, 255)
CANVAS_BORDER_COLOR = (200, 200, 200)
BUTTON_COLOR = (0, 136, 204)
TEXT_COLOR = (0, 0, 0)
RED_COLOR = (255, 0, 0)
GREEN_COLOR = (0, 160, 80)

PRESET_SIZES = [
    ("巨量/小红书竖版", 1080, 1920),
    ("全平台方形", 800, 800),
    ("百度/头条横版", 1280, 720),
    ("小红书方形", 1080, 1080),
    ("微信H5适配", 750, 1334)
]

CONFIG_FILE = os.path.join(BASE_DIR, "canvas_config.json")
UNDO_LIMIT = 50
SNAP_THRESHOLD = 10
MAX_VISIBLE_MATERIALS = 5
THUMB_SIZE = (32, 32)
MAX_PREGEN = 300

# ===================== 核心类 =====================
class MaterialGenerator:
    def __init__(self):
        self.screen = pygame.display.set_mode(WINDOW_SIZE)
        pygame.display.set_caption("投放素材生成器")

        self.font = self.load_chinese_font(22)
        self.small_font = self.load_chinese_font(16)

        self.canvas_width, self.canvas_height = self.load_canvas_config()
        self.current_preset = self.get_current_preset_name()
        self.size_dropdown_open = False

        self.material_groups = {}
        self.thumb_cache = {}
        self.load_materials()
        
        self.canvas_items = []
        self.selected_item = None
        self.drag_offset = (0, 0)
        self.moved_flag = False

        self.undo_stack = []
        self.material_scroll = 0

        self.w_txt = str(self.canvas_width).lstrip("0")
        self.h_txt = str(self.canvas_height).lstrip("0")
        self.input_w_active = False
        self.input_h_active = False

        self.batch_count_txt = "20"
        self.diff_count_txt = "3"
        self.batch_count_active = False
        self.diff_count_active = False
        
        self.valid_combinations = []
        self.real_max_export = 0
        self.export_msg = ""
        self.update_real_max_export()

        self.init_ui()
        self.save_state()
        self.clock = pygame.time.Clock()

    def load_chinese_font(self, size):
        font_candidates = [
            ("/System/Library/Fonts/PingFang.ttc", 0),
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/Library/Fonts/Arial Unicode MS.ttf"
        ]
        for fp in font_candidates:
            try:
                if isinstance(fp, tuple):
                    return pygame.font.Font(fp[0], size)
                elif os.path.exists(fp):
                    return pygame.font.Font(fp, size)
            except:
                continue
        return pygame.font.SysFont("Arial Unicode MS", size)

    def load_canvas_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE,"r",encoding="utf-8") as f:
                    c = json.load(f)
                    w = max(100, min(4096, c.get("width", 1280)))
                    h = max(100, min(4096, c.get("height", 720)))
                    return w,h
        except:
            pass
        return 1280, 720

    def save_canvas_config(self):
        try:
            with open(CONFIG_FILE,"w",encoding="utf-8") as f:
                json.dump({"width":self.canvas_width,"height":self.canvas_height},f,indent=2)
        except:
            pass

    def get_current_preset_name(self):
        for name, w, h in PRESET_SIZES:
            if w == self.canvas_width and h == self.canvas_height:
                return f"{name} {w}×{h}"
        return f"自定义尺寸 {self.canvas_width}×{self.canvas_height}"
        
    def update_real_max_export(self):
        try:
            min_diff = int(self.diff_count_txt)
        except:
            self.real_max_export = 0
            self.valid_combinations = []
            self.export_msg = "请输入有效数字"
            return

        base = [it.copy() for it in self.canvas_items]
        changeable = []
        option_pool = {}

        for idx, item in enumerate(base):
            g = item["group"]
            fs = self.material_groups.get(g, {}).get("files", [])
            if len(fs) >= 2:
                changeable.append(idx)
                option_pool[idx] = [f for f in fs if f != item["file"]]

        total_changeable = len(changeable)
        if min_diff < 1 or total_changeable < min_diff:
            self.real_max_export = 0
            self.valid_combinations = []
            self.export_msg = f"可替换{total_changeable}个 < 最小差异{min_diff}个"
            return

        all_candidates = []
        try:
            pos_list = list(itertools.combinations(changeable, min_diff))
            random.shuffle(pos_list)
            for positions in pos_list[:MAX_PREGEN]:
                opt_list = [option_pool[p] for p in positions]
                for file_comb in itertools.product(*opt_list):
                    temp = [it.copy() for it in base]
                    key = []
                    for i, p in enumerate(positions):
                        temp[p]["file"] = file_comb[i]
                        key.append((p, file_comb[i]))
                    all_candidates.append((temp, tuple(sorted(key))))
        except:
            pass

        valid = []
        used_keys = set()
        for item, key in all_candidates:
            if key in used_keys:
                continue

            ok = True
            for v_item in valid:
                diff = 0
                for i in range(len(item)):
                    if item[i]["file"] != v_item[i]["file"]:
                        diff += 1
                        if diff >= min_diff:
                            break
                if diff < min_diff:
                    ok = False
                    break
            if ok:
                used_keys.add(key)
                valid.append(item)

        self.valid_combinations = valid
        self.real_max_export = len(valid)
        self.export_msg = "" if self.real_max_export else "无满足条件组合"

    def save_state(self):
        cp = [it.copy() for it in self.canvas_items]
        self.undo_stack.append({
            "items": cp, 
            "cw": self.canvas_width, 
            "ch": self.canvas_height
        })
        if len(self.undo_stack) > UNDO_LIMIT:
            self.undo_stack.pop(0)

    def undo(self):
        if len(self.undo_stack) > 1:
            self.undo_stack.pop()
            s = self.undo_stack[-1]
            self.canvas_items = s["items"]
            self.canvas_width = s["cw"]
            self.canvas_height = s["ch"]
            self.w_txt = str(self.canvas_width).lstrip("0")
            self.h_txt = str(self.canvas_height).lstrip("0")
            self.current_preset = self.get_current_preset_name()
            self.update_real_max_export()

    def load_materials(self):
        self.material_groups = {}
        self.thumb_cache = {}
        if not os.path.exists(MATERIALS_FOLDER):
            os.makedirs(MATERIALS_FOLDER)
            return
        for name in sorted(os.listdir(MATERIALS_FOLDER)):
            p = os.path.join(MATERIALS_FOLDER, name)
            if not os.path.isdir(p) or name.startswith("."):
                continue
            imgs = [f for f in os.listdir(p) if f.lower().endswith((".png",".jpg",".jpeg",".webp"))]
            if imgs:
                self.material_groups[name] = {"path": p, "files": sorted(imgs)}
                self.load_thumbnail(name, imgs[0])
        self.update_real_max_export()

    def load_thumbnail(self, g, f):
        path = os.path.join(self.material_groups[g]["path"], f)
        try:
            im = Image.open(path).convert("RGBA")
            im.thumbnail(THUMB_SIZE)
            self.thumb_cache[g] = pygame.image.fromstring(im.tobytes(), im.size, "RGBA")
        except:
            s = pygame.Surface(THUMB_SIZE, pygame.SRCALPHA)
            pygame.draw.rect(s, (200,200,200), (0,0,*THUMB_SIZE))
            self.thumb_cache[g] = s

    def load_image(self, g, f):
        path = os.path.join(self.material_groups[g]["path"], f)
        im = Image.open(path).convert("RGBA")
        return pygame.image.fromstring(im.tobytes(), im.size, "RGBA"), im.width, im.height

    def add_material(self, g):
        if g not in self.material_groups:
            return
        f = random.choice(self.material_groups[g]["files"])
        surf, w, h = self.load_image(g, f)
        item = {
            "group":g, "file":f,
            "x":(self.canvas_width-w)//2, "y":(self.canvas_height-h)//2,
            "w":w, "h":h, "surf":surf
        }
        self.canvas_items.append(item)
        self.selected_item = item
        self.save_state()
        self.update_real_max_export()

    def clear_all(self):
        if self.canvas_items:
            self.save_state()
            self.canvas_items.clear()
            self.selected_item = None
            self.update_real_max_export()

    def export_single(self, items, path):
        bg = Image.new("RGBA", (self.canvas_width, self.canvas_height), (255,255,255))
        for it in items:
            im = Image.open(os.path.join(self.material_groups[it["group"]]["path"], it["file"])).convert("RGBA")
            bg.paste(im, (int(it["x"]), int(it["y"])), im)
        bg.save(path)

    def batch_export(self):
        if not self.canvas_items:
            self.export_msg = "画布无素材"
            return
        
        try:
            user_want = int(self.batch_count_txt.strip())
            min_diff = int(self.diff_count_txt.strip())
        except:
            self.export_msg = "数字输入错误"
            return

        if self.real_max_export < 1:
            self.export_msg = "无满足差异条件的素材"
            return

        export_num = min(user_want, self.real_max_export)
        export_list = self.valid_combinations[:export_num]

        folder = os.path.join(BASE_DIR, f"批量导出_{len(export_list)}张_两两至少{min_diff}处差异")
        os.makedirs(folder, exist_ok=True)
        for i, items in enumerate(export_list):
            self.export_single(items, os.path.join(folder, f"batch_{i+1:03d}.png"))
        
        self.export_msg = f"✅ 成功导出{len(export_list)}张"

    def snap(self, item, x, y):
        cx, cy, w, h = self.canvas_width, self.canvas_height, item["w"], item["h"]
        snaps = [(0,y),(cx-w,y),(x,0),(x,cy-h),((cx-w)/2,y),(x,(cy-h)/2)]
        best, min_d = (x,y), 9999
        for sx, sy in snaps:
            d = ((sx-x)**2 + (sy-y)**2)**0.5
            if d < SNAP_THRESHOLD and d < min_d:
                best, min_d = (sx,sy), d
        return max(0, min(best[0], cx-w)), max(0, min(best[1], cy-h))

    def init_ui(self):
        ui_x = WINDOW_SIZE[0] - UI_WIDTH
        self.size_btn = pygame.Rect(ui_x+20,50,UI_WIDTH-40,40)
        self.input_w = pygame.Rect(ui_x+20,110,100,40)
        self.input_h = pygame.Rect(ui_x+130,110,100,40)
        self.confirm_size = pygame.Rect(ui_x+20,160,UI_WIDTH-40,40)
        self.btn_undo = pygame.Rect(ui_x+20,210,UI_WIDTH-40,40)
        self.btn_clear = pygame.Rect(ui_x+20,260,UI_WIDTH-40,40)
        self.batch_count_input = pygame.Rect(ui_x+130,320,100,40)
        self.diff_count_input = pygame.Rect(ui_x+130,370,100,40)
        self.btn_export = pygame.Rect(ui_x+20,470,UI_WIDTH-40,40)

    def handle(self):
        mx, my = pygame.mouse.get_pos()
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.save_canvas_config()
                pygame.quit()
                sys.exit()

            if e.type == pygame.MOUSEWHEEL:
                mat_rect = pygame.Rect(WINDOW_SIZE[0]-UI_WIDTH+20,560,UI_WIDTH-40,MAX_VISIBLE_MATERIALS*40)
                if mat_rect.collidepoint((mx,my)) and not self.size_dropdown_open:
                    total = len(self.material_groups)
                    self.material_scroll = max(0, min(self.material_scroll-e.y, total-MAX_VISIBLE_MATERIALS))

            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                self.moved_flag = False
                self.export_msg = ""

                if self.size_dropdown_open:
                    drop_rect = pygame.Rect(self.size_btn.x, self.size_btn.bottom, self.size_btn.width, len(PRESET_SIZES)*40)
                    if drop_rect.collidepoint((mx,my)):
                        for i,(name,w,h) in enumerate(PRESET_SIZES):
                            opt_rect = pygame.Rect(self.size_btn.x, self.size_btn.bottom+i*40, self.size_btn.width,40)
                            if opt_rect.collidepoint((mx,my)):
                                self.canvas_width, self.canvas_height = w,h
                                self.w_txt = str(w)
                                self.h_txt = str(h)
                                self.current_preset = f"{name} {w}×{h}"
                                self.save_state()
                        self.size_dropdown_open = False
                        continue
                if self.size_btn.collidepoint((mx,my)):
                    self.size_dropdown_open = not self.size_dropdown_open
                    continue

                if self.btn_undo.collidepoint((mx,my)):
                    self.undo()
                    continue
                if self.btn_clear.collidepoint((mx,my)):
                    self.clear_all()
                    continue
                if self.confirm_size.collidepoint((mx,my)):
                    try:
                        w,h = int(self.w_txt),int(self.h_txt)
                        if 100<=w<=4096 and 100<=h<=4096:
                            self.canvas_width, self.canvas_height = w,h
                            self.current_preset = self.get_current_preset_name()
                            self.save_state()
                    except:
                        pass
                    continue
                if self.btn_export.collidepoint((mx,my)):
                    self.batch_export()
                    continue

                self.input_w_active = self.input_w.collidepoint((mx,my))
                self.input_h_active = self.input_h.collidepoint((mx,my))
                self.batch_count_active = self.batch_count_input.collidepoint((mx,my))
                self.diff_count_active = self.diff_count_input.collidepoint((mx,my))

                ui_x = WINDOW_SIZE[0]-UI_WIDTH
                groups = list(self.material_groups.keys())
                vis = groups[self.material_scroll:self.material_scroll+MAX_VISIBLE_MATERIALS]
                for i,g in enumerate(vis):
                    r = pygame.Rect(ui_x+20,560+i*40,UI_WIDTH-40,36)
                    if r.collidepoint((mx,my)):
                        self.add_material(g)
                        break

                self.selected_item = None
                cr = self.canvas_rect()
                if cr.collidepoint((mx,my)):
                    s = self.scale()
                    cx, cy = (mx-cr.x)/s, (my-cr.y)/s
                    for it in reversed(self.canvas_items):
                        if it["x"] <= cx <= it["x"]+it["w"] and it["y"] <= cy <= it["y"]+it["h"]:
                            self.selected_item = it
                            self.drag_offset = (cx-it["x"], cy-it["y"])
                            break

            if e.type == pygame.MOUSEMOTION and self.selected_item and pygame.mouse.get_pressed()[0] and not self.size_dropdown_open:
                cr = self.canvas_rect()
                if not cr.collidepoint((mx,my)):
                    return
                s = self.scale()
                cx, cy = (mx-cr.x)/s - self.drag_offset[0], (my-cr.y)/s - self.drag_offset[1]
                self.selected_item["x"], self.selected_item["y"] = self.snap(self.selected_item, cx, cy)
                self.moved_flag = True

            if e.type == pygame.MOUSEBUTTONUP and e.button == 1 and self.moved_flag and self.selected_item:
                self.save_state()
                self.moved_flag = False

            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_r and self.selected_item:
                    it = self.selected_item
                    g = it["group"]
                    fs = [f for f in self.material_groups[g]["files"] if f != it["file"]]
                    if fs:
                        nf = random.choice(fs)
                        surf,w,h = self.load_image(g,nf)
                        it.update(file=nf, surf=surf, w=w, h=h)
                        self.save_state()
                        self.update_real_max_export()
                if e.key == pygame.K_s:
                    self.export_single(self.canvas_items, os.path.join(BASE_DIR, f"单张导出_{pygame.time.get_ticks()}.png"))
                if e.key == pygame.K_z and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                    self.undo()

                update_flag = False
                if self.input_w_active:
                    update_flag = True
                    self.w_txt = self.w_txt[:-1] if e.key == pygame.K_BACKSPACE else (self.w_txt + e.unicode if e.unicode.isdigit() and len(self.w_txt)<4 else self.w_txt)
                if self.input_h_active:
                    update_flag = True
                    self.h_txt = self.h_txt[:-1] if e.key == pygame.K_BACKSPACE else (self.h_txt + e.unicode if e.unicode.isdigit() and len(self.h_txt)<4 else self.h_txt)
                if self.batch_count_active:
                    update_flag = True
                    self.batch_count_txt = self.batch_count_txt[:-1] if e.key == pygame.K_BACKSPACE else (self.batch_count_txt + e.unicode if e.unicode.isdigit() else self.batch_count_txt)
                if self.diff_count_active:
                    update_flag = True
                    self.diff_count_txt = self.diff_count_txt[:-1] if e.key == pygame.K_BACKSPACE else (self.diff_count_txt + e.unicode if e.unicode.isdigit() else self.diff_count_txt)
                if update_flag:
                    self.update_real_max_export()

    def scale(self):
        return min((WINDOW_SIZE[0]-UI_WIDTH-40)/self.canvas_width, (WINDOW_SIZE[1]-40)/self.canvas_height, 0.8)

    def canvas_rect(self):
        s = self.scale()
        w, h = int(self.canvas_width*s), int(self.canvas_height*s)
        return pygame.Rect((WINDOW_SIZE[0]-UI_WIDTH-w)//2+20, (WINDOW_SIZE[1]-h)//2+20, w, h)

    def draw(self):
        self.screen.fill(WINDOW_BG_COLOR)
        cr, s, ui_x = self.canvas_rect(), self.scale(), WINDOW_SIZE[0]-UI_WIDTH

        pygame.draw.rect(self.screen, CANVAS_BG_COLOR, cr)
        pygame.draw.rect(self.screen, CANVAS_BORDER_COLOR, cr, 2)
        for it in self.canvas_items:
            px = cr.x + int(it["x"]*s)
            py = cr.y + int(it["y"]*s)
            surf = pygame.transform.scale(it["surf"], (int(it["w"]*s), int(it["h"]*s)))
            self.screen.blit(surf, (px,py))
            if it == self.selected_item:
                pygame.draw.rect(self.screen, RED_COLOR, (px,py,int(it["w"]*s),int(it["h"]*s)), 2)

        pygame.draw.line(self.screen, (200,200,200), (ui_x,0), (ui_x,WINDOW_SIZE[1]))

        pygame.draw.rect(self.screen, BUTTON_COLOR, self.size_btn)
        t = self.small_font.render(self.current_preset, True, (255,255,255))
        self.screen.blit(t, t.get_rect(center=self.size_btn.center))

        self.screen.blit(self.small_font.render("自定义尺寸",True,TEXT_COLOR),(ui_x+20,90))
        for box,act,txt in [(self.input_w,self.input_w_active,self.w_txt),(self.input_h,self.input_h_active,self.h_txt)]:
            pygame.draw.rect(self.screen,(245,245,245),box)
            pygame.draw.rect(self.screen,(0,0,0)if act else(200,200,200),box,2)
            if txt:
                self.screen.blit(self.small_font.render(txt,True,TEXT_COLOR), self.small_font.render(txt,True,TEXT_COLOR).get_rect(center=box.center))

        for btn,txt,clr in [(self.confirm_size,"确认尺寸",BUTTON_COLOR),(self.btn_undo,"撤回",BUTTON_COLOR),(self.btn_clear,"清空画布",(220,60,60))]:
            pygame.draw.rect(self.screen, clr, btn)
            self.screen.blit(self.small_font.render(txt,True,(255,255,255)), self.small_font.render(txt,True,(255,255,255)).get_rect(center=btn.center))

        self.screen.blit(self.small_font.render("批量导出设置",True,TEXT_COLOR),(ui_x+20,300))
        self.screen.blit(self.small_font.render("导出张数：",True,TEXT_COLOR),(ui_x+20,330))
        pygame.draw.rect(self.screen,(245,245,245),self.batch_count_input)
        pygame.draw.rect(self.screen,(0,0,0)if self.batch_count_active else(200,200,200),self.batch_count_input,2)
        self.screen.blit(self.small_font.render(self.batch_count_txt,True,TEXT_COLOR), self.small_font.render(self.batch_count_txt,True,TEXT_COLOR).get_rect(center=self.batch_count_input.center))

        self.screen.blit(self.small_font.render("最小差异数：",True,TEXT_COLOR),(ui_x+20,380))
        pygame.draw.rect(self.screen,(245,245,245),self.diff_count_input)
        pygame.draw.rect(self.screen,(0,0,0)if self.diff_count_active else(200,200,200),self.diff_count_input,2)
        self.screen.blit(self.small_font.render(self.diff_count_txt,True,TEXT_COLOR), self.small_font.render(self.diff_count_txt,True,TEXT_COLOR).get_rect(center=self.diff_count_input.center))

        self.screen.blit(self.small_font.render(f"最大可导出：{self.real_max_export} 张",True,RED_COLOR),(ui_x+20, 410))
        msg_color = GREEN_COLOR if "✅" in self.export_msg else RED_COLOR
        self.screen.blit(self.small_font.render(self.export_msg,True,msg_color),(ui_x+20, 435))

        pygame.draw.rect(self.screen, GREEN_COLOR, self.btn_export)
        self.screen.blit(self.small_font.render("开始批量导出",True,(255,255,255)), self.small_font.render("开始批量导出",True,(255,255,255)).get_rect(center=self.btn_export.center))

        self.screen.blit(self.font.render("素材组件",True,TEXT_COLOR),(ui_x+20,520))
        groups = list(self.material_groups.keys())
        vis = groups[self.material_scroll:self.material_scroll+MAX_VISIBLE_MATERIALS]
        for i,g in enumerate(vis):
            r = pygame.Rect(ui_x+20,560+i*40,UI_WIDTH-40,36)
            pygame.draw.rect(self.screen,(235,235,235),r)
            if g in self.thumb_cache:
                self.screen.blit(self.thumb_cache[g],(r.x+6,r.y+2))
            self.screen.blit(self.small_font.render(g,True,TEXT_COLOR),(r.x+44,r.y+8))

        if self.size_dropdown_open:
            drop_rect = pygame.Rect(self.size_btn.x,self.size_btn.bottom,self.size_btn.width,len(PRESET_SIZES)*40)
            pygame.draw.rect(self.screen,(255,255,255),drop_rect)
            pygame.draw.rect(self.screen,(200,200,200),drop_rect,2)
            for i,(name,w,h) in enumerate(PRESET_SIZES):
                opt_rect = pygame.Rect(self.size_btn.x,self.size_btn.bottom+i*40,self.size_btn.width,40)
                self.screen.blit(self.small_font.render(f"{name} {w}×{h}",True,TEXT_COLOR),(opt_rect.x+10,opt_rect.y+10))

        self.screen.blit(self.small_font.render(f"当前：{self.canvas_width}×{self.canvas_height}",True,TEXT_COLOR),(cr.x,cr.bottom+10))
        self.screen.blit(self.small_font.render("S=单张 | R=换图 | Ctrl+Z=撤回",True,TEXT_COLOR),(20,20))
        pygame.display.flip()

    def run(self):
        while True:
            self.handle()
            self.draw()
            self.clock.tick(60)

if __name__ == "__main__":
    app = MaterialGenerator()
    app.run()