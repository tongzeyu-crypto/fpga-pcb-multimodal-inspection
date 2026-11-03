"""A labeled result sheet, not a photograph or a board HDMI screenshot."""
from pathlib import Path
import argparse,json,math
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();data=json.loads((a.run/'demo-result.json').read_text())
    image=Image.new('RGB',(2000,1320),'#0b1520');draw=ImageDraw.Draw(image)
    def font(size):
        for path in ['C:/Windows/Fonts/msyh.ttc','C:/Windows/Fonts/simhei.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']:
            if Path(path).exists():return ImageFont.truetype(path,size)
        return ImageFont.load_default()
    def text(x,y,s,size=24,color='#dce8f5'):draw.text((x,y),s,font=font(size),fill=color)
    def panel(box,title):draw.rounded_rectangle(box,16,fill='#152332',outline='#304456',width=2);text(box[0]+24,box[1]+19,title,27)
    text(50,28,'PL / PS 功能演示',42);text(50,91,'模拟机构  ·  历史原始数据回放  ·  AXI RTL 仿真结果',26,'#efc56f')
    text(1320,38,'6 测点 / 18 帧 / 21 次 PL 结果调用',25,'#60d4bc');text(1320,88,'独立演示核 · 已核验XSim结果回放',20)
    panel((50,170,975,690),'PS 扫描调度');panel((1025,170,1950,690),'PL 64 点频谱核心');panel((50,725,975,1230),'PL 温度转换 / 热点计数');panel((1025,725,1950,1230),'共享像素预处理：分时使用')
    points=data['points'];xs=[p['xy_mm'][0] for p in points];ys=[p['xy_mm'][1] for p in points]
    positions=[(160+(p['xy_mm'][0]-min(xs))/max(1,max(xs)-min(xs))*680,290+(p['xy_mm'][1]-min(ys))/max(1,max(ys)-min(ys))*230) for p in points]
    for start,end in zip(positions,positions[1:]):
        draw.line([start,end],fill='#54cdbd',width=5);mx,my=(start[0]+end[0])/2,(start[1]+end[1])/2;angle=math.atan2(end[1]-start[1],end[0]-start[0]);tip=(mx+10*math.cos(angle),my+10*math.sin(angle));draw.polygon([tip,(mx-8*math.cos(angle)+7*math.sin(angle),my-8*math.sin(angle)-7*math.cos(angle)),(mx-8*math.cos(angle)-7*math.sin(angle),my-8*math.sin(angle)+7*math.cos(angle))],fill='#54cdbd')
    for point,(x,y) in zip(points,positions):
        draw.ellipse((x-23,y-23,x+23,y+23),fill='#286d68',outline='#79f3d8',width=2);text(x-8,y-17,str(point['ordinal']+1),23);text(x-50,y+32,f"({point['xy_mm'][0]:g}, {point['xy_mm'][1]:g})",21)
    text(78,592,'MOVE → 确认 Idle / 坐标 → 停稳 → 采样×3 → 关联',21)
    text(78,636,f"停稳设置 {points[0]['settle_s']*1000:g} ms；坐标为控制流程演示",20,'#9bb3c8')
    powers=points[0]['mean_power'];values=[10*math.log10(v+1) for v in powers];maximum=max(10,max(values));left,top,width,height=1100,275,770,280
    for i in range(5):
        y=top+height-i*height/4;draw.line((left,y,left+width,y),fill='#304456');text(left-57,y-10,f'{maximum*i/4:.0f}',17,'#9bb3c8')
    curve=[(left+i*width/32,top+height-v/maximum*height) for i,v in enumerate(values)];draw.line(curve,fill='#70d8ff',width=4)
    for i in range(5):text(left+i*width/4-18,top+height+12,f'{i*6.25:g}',18,'#9bb3c8')
    peak=max(range(1,33),key=lambda i:powers[i]);text(1070,221,f"第一测点三帧平均；峰值格点 {peak*50/64:.3f} MHz",22)
    text(1070,606,'频率 / MHz   ·   相对功率显示，未标定场强',20,'#9bb3c8');text(1070,642,'64 点 DFT + 整数去均值；并非正式 4096 点 FFT',20,'#efc56f')
    temperatures=data['thermal']['output'];stats=data['thermal']['statistics'];low=min(temperatures);high=max(temperatures)
    def color(value):
        z=max(0,min(1,(value-low)/max(1,high-low)));return (int(35+220*z),int(70+160*(1-abs(z-.5)*2)),int(220-185*z))
    x0,y0=85,825
    for i,t in enumerate(temperatures):
        x=i%16;y=i//16;draw.rectangle((x0+x*25,y0+y*18.75,x0+(x+1)*25,y0+(y+1)*18.75),fill=color(t))
    mx,my=stats['max_index']%16,stats['max_index']//16;cx=x0+(mx+.5)*25;cy=y0+(my+.5)*18.75;draw.ellipse((cx-11,cy-11,cx+11,cy+11),outline='white',width=3)
    text(545,839,f"最低 {stats['min_mc']/1000:.3f} °C",25);text(545,897,f"最高 {stats['max_mc']/1000:.3f} °C",25);text(545,955,f"≥40°C：{stats['hot_count']} / 256 像素",24)
    text(545,1013,f'峰值原矩阵坐标 ({mx*16}, {my*12})',21);text(85,1160,'仅统计 16×16 子采样格；不是整帧热点检测或测温标定',20,'#efc56f')
    for label,key,x in [('RGB 灰度 → INT8','rgb_int8',1100),('热像裁剪 → INT8','thermal_int8',1530)]:
        values=data['preprocessing'][key]['output'];tile=Image.new('L',(16,16));tile.putdata([v+128 for v in values]);image.paste(tile.resize((280,280),Image.Resampling.NEAREST),(x,840));text(x,1140,label,23)
    text(1070,1193,'共享状态机 / RAM 通路；不包含完整缩放、Sobel 链',19,'#9bb3c8')
    text(50,1263,'独立算子与调度演示  |  模拟机构 / 历史数据 / XSim结果  |  整机实板记录单独归档',23,'#9bb3c8')
    image.save(a.run/'demo-preview.png');print(a.run/'demo-preview.png')
if __name__=='__main__':main()
