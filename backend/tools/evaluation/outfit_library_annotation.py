"""Build a blinded, image-embedded outfit-library annotation pilot from retained candidates."""
from pathlib import Path
from io import BytesIO
import random
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.formatting.rule import FormulaRule
from openpyxl.comments import Comment
from openpyxl.utils import get_column_letter
from tools.evaluation.paths import PROJECT_ROOT, evaluation_path

ROOT = PROJECT_ROOT
SOURCE = evaluation_path('recognition', 'multi_occasion', 'annotation.xlsx')
OUTPUT = evaluation_path('outfits', 'library_pilot', 'outfit_annotation.xlsx')
NAVY, TEAL, LIGHT, INK = '17324D', '177E89', 'EAF5F5', '203547'


def dropdown(sheet, options, ranges):
    dv = DataValidation(type='list', formula1='"' + ','.join(options) + '"', allow_blank=True)
    dv.showErrorMessage = True
    dv.errorTitle = '请选择下拉选项'
    dv.error = '使用下拉列表；暂时无法判断时请选择“无法判断”。'
    dv.errorStyle = 'stop'
    dv.showInputMessage = True
    dv.promptTitle = '独立判断'
    dv.prompt = '忽略天气与场合；不要根据其他评分自动填写。'
    sheet.add_data_validation(dv)
    for area in ranges: dv.add(area)


def heading(sheet, text, subtitle, headers):
    n = len(headers)
    sheet.merge_cells(start_row=1,start_column=1,end_row=1,end_column=n)
    sheet['A1'] = text
    sheet['A1'].font = Font(name='Aptos',size=22,bold=True,color='FFFFFF')
    sheet['A1'].fill = PatternFill('solid',fgColor=NAVY)
    sheet['A1'].alignment = Alignment(vertical='center')
    sheet.row_dimensions[1].height=42
    sheet.merge_cells(start_row=2,start_column=1,end_row=2,end_column=n)
    sheet['A2'] = subtitle
    sheet['A2'].font = Font(name='Aptos',size=11,color=INK)
    sheet['A2'].alignment = Alignment(wrap_text=True,vertical='center')
    sheet.row_dimensions[2].height=34
    sheet.sheet_view.showGridLines=False
    for c,value in enumerate(headers,1):
        cell=sheet.cell(4,c,value)
        cell.font=Font(name='Aptos',size=11,bold=True,color='FFFFFF')
        cell.fill=PatternFill('solid',fgColor=TEAL)
        cell.alignment=Alignment(wrap_text=True,vertical='center',horizontal='center')
    sheet.row_dimensions[4].height=42


def build():
    if OUTPUT.exists(): raise FileExistsError(OUTPUT)
    old=load_workbook(SOURCE)
    source=old['Outfit Judgments']
    images={image.anchor._from.row+1:image for image in source._images}
    # Uniform sampling of unique combinations, without consulting old human or machine labels.
    unique={}
    for r in range(3,source.max_row+1):
        codes=source.cell(r,3).value
        if r in images and codes:
            unique.setdefault(tuple(sorted(codes.split(' | '))),r)
    rng=random.Random(20260929)
    chosen=rng.sample(list(unique.values()),50)
    holdout=set(rng.sample(range(50),15))
    wb=Workbook();main=wb.active;main.title='搭配标注'
    instructions=wb.create_sheet('填写说明')
    model=wb.create_sheet('模型评估')
    headers=['Outfit ID','搭配图片','单品编号','结构可穿','美观程度\n1–5 分','我愿意穿','修改建议／备注',
             '缺主要单品','单品角色冲突','叠穿不合理','图片信息不足','配色问题','轮廓比例问题','材质组合问题','风格组合问题','其他问题','完成状态']
    heading(main,'搭配库 · 人工标注 / PILOT 01','只看搭配本身，忽略天气和场合。先填 D–F 三项；右侧问题列有问题选 ✓，无问题留空。',headers)
    widths=[13,65,23,16,15,16,34,12,13,13,13,12,14,14,14,12,14]
    for i,width in enumerate(widths,1):main.column_dimensions[get_column_letter(i)].width=width
    main.freeze_panes='D5';main.sheet_view.zoomScale=80
    main.auto_filter.ref='A4:Q54'
    main.print_title_rows='1:4';main.print_options.horizontalCentered=True
    main.sheet_properties.pageSetUpPr.fitToPage=True
    main.page_setup.orientation='landscape';main.page_setup.paperSize=main.PAPERSIZE_A3
    main.page_setup.fitToWidth=1;main.page_setup.fitToHeight=0
    main.print_area='A1:G54'
    dropdown(main,['可以','不可以','无法判断'],['D5:D54'])
    dropdown(main,['1','2','3','4','5','无法判断'],['E5:E54'])
    dropdown(main,['愿意','不确定','不愿意','无法判断'],['F5:F54'])
    dropdown(main,['✓'],['H5:P54'])
    definitions={
      'D4':'只判断单品是否能合理组成一套衣服：角色完整、叠穿合理。暂不要求鞋包配饰齐全；不考虑温度和场合。',
      'E4':'1 明显不协调；2 需要替换主要单品；3 普通能接受；4 协调好看；5 非常喜欢视觉效果。无法判断不等于 3 分。',
      'F4':'是否符合自己的风格与舒适偏好；不考虑今天的天气或活动。',
      'H4':'缺上衣或下装等主要单品；没有鞋包不自动算不完整。',
      'K4':'图片不足以确认长度、厚度、轮廓等；必要时主评分选择无法判断。'}
    for cell,value in definitions.items():main[cell].comment=Comment(value,'填写指南')
    mh=['Outfit ID','原始 Outfit ID','原始 Excel 行','候选来源','数据划分','模型版本／提示词版本','模型结构可穿','模型美观 1–5','模型预测愿意穿','模型建议入库','结构判断理由','美观判断理由','评分时间','人工结构可穿','人工美观','人工愿意穿','人工质量通过','模型入库且人工通过']
    heading(model,'模型评估 · 标注时请保持隐藏','模型结果暂不填。开发集 35 套、留出验证集 15 套；留出集不得用于调提示词。',mh)
    for c in range(1,len(mh)+1):model.column_dimensions[get_column_letter(c)].width=24
    model.freeze_panes='B5';model.auto_filter.ref='A4:R54'
    dropdown(model,['可以','不可以','无法判断'],['G5:G54'])
    dropdown(model,['1','2','3','4','5','无法判断'],['H5:H54'])
    dropdown(model,['愿意','不确定','不愿意','无法判断'],['I5:I54'])
    dropdown(model,['是','否'],['J5:J54'])
    for index,source_row in enumerate(chosen):
        r=index+5;identifier=f'P{index+1:03d}'
        main.cell(r,1,identifier);main.cell(r,3,source.cell(source_row,3).value)
        main.cell(r,17,f'=IF(COUNTA(D{r}:F{r})=0,"未开始",IF(COUNTA(D{r}:F{r})<3,"待补全",IF(COUNTIF(D{r}:F{r},"无法判断")>0,"已填·需复核","已完成")))')
        main.row_dimensions[r].height=175
        image=Image(BytesIO(images[source_row]._data()))
        scale=min(440/image.width,210/image.height)
        image.width*=scale;image.height*=scale
        main.add_image(image,f'B{r}')
        for c in range(1,18):
            cell=main.cell(r,c);cell.font=Font(name='Aptos',size=11,color=INK)
            cell.alignment=Alignment(vertical='center',horizontal='center' if c!=7 else 'left',wrap_text=True)
            cell.fill=PatternFill('solid',fgColor=('EDF8F4' if 4<=c<=6 else 'F3F6F9' if index%2==0 else 'FFFFFF'))
            cell.border=Border(bottom=Side(style='hair',color='D5DEE8'))
        values=[identifier,source.cell(source_row,2).value,source_row,'既有随机结构候选；未按旧评分筛选','留出验证' if index in holdout else '开发']
        for c,v in enumerate(values,1):model.cell(r,c,v)
        for c,source_col in [(14,'D'),(15,'E'),(16,'F')]:model.cell(r,c,f'=IF(\'搭配标注\'!{source_col}{r}="","",\'搭配标注\'!{source_col}{r})')
        model.cell(r,17,f'=IF(OR(N{r}="",O{r}="",N{r}="无法判断",O{r}="无法判断"),"",IF(AND(N{r}="可以",IFERROR(VALUE(O{r}),0)>=4),1,0))')
        model.cell(r,18,f'=IF(OR(J{r}="",Q{r}=""),"",IF(J{r}="是",Q{r},""))')
    for text,color in [('已完成','D9EEDB'),('待补全','FFF0C2'),('已填·需复核','FFE1CF')]:
        main.conditional_formatting.add('Q5:Q54',FormulaRule(formula=[f'Q5="{text}"'],fill=PatternFill('solid',fgColor=color)))
    heading(instructions,'填写说明 · 先看这里','这一轮先回答“能合理穿吗、好看吗、我想穿吗”，三项独立判断。',['主题','说明'])
    instructions.column_dimensions['A'].width=26;instructions.column_dimensions['B'].width=115
    notes=[
      ('如何开始','打开“搭配标注”，按每行图片填写 D、E、F。绿色单元格为三项主评价；其他问题和文字说明均选填。'),
      ('结构可穿','可以／不可以／无法判断。考虑主要单品角色和叠穿关系；鞋、包、配饰不要求齐全。不要把不喜欢或天气不合适当成结构不合理。'),
      ('美观 1 分','明显不协调。'),('美观 2 分','有明显问题，需要替换主要单品。'),('美观 3 分','普通、能接受，但没有特别喜欢。'),('美观 4 分','协调、好看。'),('美观 5 分','非常喜欢这套搭配的视觉效果。'),
      ('无法判断','平铺图看不出实际轮廓、长度或叠穿厚度时，可以选择“无法判断”；不要用 3 分代替。'),
      ('我愿意穿','愿意／不确定／不愿意／无法判断。考虑自己的风格、舒适度和接受程度；不考虑今天的场合天气。好看但不想穿是有效答案。'),
      ('问题标签','右侧 H–P 各列独立选择 ✓；可同时选多个。空白表示未勾选，不能据此认定已完整检查所有问题。其他具体原因写在 G 列。'),
      ('独立填写','三个主评价独立填写；结构不合理不自动等于美观 1 分。不要查看模型结果或旧 Excel 的评分。'),
      ('本批样本','从保留的旧 Sheet2 中，按固定随机种子抽取 50 套不重复候选，重新随机展示；没有使用旧人工或模型评分挑选。图片嵌入 Excel，离线可看。'),
      ('样本限制','本批全是既有候选，不是假称的“10 套你认可的搭配＋10 套已知错误”。你的正面参考和刻意错误案例尚未收集；本表用于第一轮重标注。'),
      ('隐藏模型表','“模型评估”默认隐藏。人工标完之后，使用 Excel 的“取消隐藏工作表”查看。模型分数和入库判断目前均为空。隐藏只用于防止无意看到，不是访问控制。'),
      ('开发与留出','后台固定分为 35 套开发、15 套留出验证。留出标签不能用于反复调整模型或提示词；此次旧样本若此前已用于调参，不能视为完全独立测试集。'),
      ('质量通过标准','结构可穿＝可以，且美观≥4。与“我愿意穿”分开统计。无法判断或缺评分的记录不纳入质量通过率分母，应单独报告覆盖率。'),
      ('核心评估','模型建议入库且人工质量通过的数量 ÷ 模型建议入库且人工质量可判断的数量。请分别报告开发集和留出集，并单独统计用户愿意穿比例。'),
      ('填写进度','以下公式在 Excel 打开时自动计算；“已填”包含无法判断，需复核会单独计数。'),
      ('已填写三项', '=COUNTIF(\'搭配标注\'!Q5:Q54,"已完成")+COUNTIF(\'搭配标注\'!Q5:Q54,"已填·需复核")'),
      ('需要复核','=COUNTIF(\'搭配标注\'!Q5:Q54,"已填·需复核")'),
      ('总样本数',50)]
    for r,(title,text) in enumerate(notes,5):
        instructions.cell(r,1,title);instructions.cell(r,2,text)
        instructions.row_dimensions[r].height=48
        for cell in instructions[r][:2]:
            cell.alignment=Alignment(vertical='center',wrap_text=True)
            cell.font=Font(name='Aptos',size=11,color=INK,bold=cell.column==1)
            cell.fill=PatternFill('solid',fgColor=LIGHT if r%2 else 'FFFFFF')
    model.sheet_state='hidden'
    wb.active=0
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    wb.save(OUTPUT)
    check=load_workbook(OUTPUT)
    assert len(check['搭配标注']._images)==50
    assert check['模型评估'].sheet_state=='hidden'
    assert sum(check['模型评估'].cell(r,5).value=='留出验证' for r in range(5,55))==15
    assert all(check['搭配标注'].cell(r,c).value is None for r in range(5,55) for c in range(4,17))
    assert len(check['搭配标注'].data_validations.dataValidation)==4
    assert len({check['搭配标注'].cell(r,3).value for r in range(5,55)})==50
    print(f'Workbook: {OUTPUT}\nVerified: 50 embedded images, blank human/model ratings, dropdowns, hidden model sheet, 35/15 split.')


if __name__=='__main__':build()
