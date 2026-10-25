"""
Tabîb Ekmeleddin (Bey Hekim) Kimdir?
13. Yüzyıl Anadolu Selçuklu Başhekimi ve Mevlânâ'nın Tabibi hakkında
ReportLab ile altın tezhip çerçeveli, şık ve Türkçe karakter destekli PDF üretir.
"""

from __future__ import annotations

import os
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer

BASE_DIR = Path(__file__).parent
OUTPUT_PDF = BASE_DIR / "assets" / "tabib_ekmeleddin_kimdir.pdf"

# Renk paleti (Selçuklu Turkuazı & Altın Tezhip Uyumu)
C_GOLD = HexColor("#c29227")
C_GOLD_LT = HexColor("#dfb558")
C_TURQUOISE = HexColor("#006d77")
C_INK = HexColor("#1c140d")
C_MUTED = HexColor("#5c4838")
C_BORDER = HexColor("#845b2f")


def register_fonts() -> str:
    """Türkçe karakter destekli sistem fontunu kaydeder."""
    font_candidates = [
        ("C:/Windows/Fonts/georgia.ttf", "Georgia", "C:/Windows/Fonts/georgiab.ttf", "C:/Windows/Fonts/georgiai.ttf", "C:/Windows/Fonts/georgiaz.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "Arial", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ariali.ttf", "C:/Windows/Fonts/arialbi.ttf"),
        ("C:/Windows/Fonts/segoeui.ttf", "SegoeUI", "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/segoeuii.ttf", "C:/Windows/Fonts/segoeuiz.ttf"),
    ]
    for path, name, bold_path, italic_path, bi_path in font_candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                b_name = f"{name}-Bold" if os.path.exists(bold_path) else name
                i_name = f"{name}-Italic" if os.path.exists(italic_path) else name
                bi_name = f"{name}-BoldItalic" if os.path.exists(bi_path) else b_name
                if os.path.exists(bold_path):
                    pdfmetrics.registerFont(TTFont(b_name, bold_path))
                if os.path.exists(italic_path):
                    pdfmetrics.registerFont(TTFont(i_name, italic_path))
                if os.path.exists(bi_path):
                    pdfmetrics.registerFont(TTFont(bi_name, bi_path))
                pdfmetrics.registerFontFamily(name, normal=name, bold=b_name, italic=i_name, boldItalic=bi_name)
                return name
            except Exception:
                pass
    return "Helvetica"


_ACTIVE_FONT = "Helvetica"


def draw_background_and_border(canvas, doc):
    """Her sayfaya Selçuklu ve Osmanlı tezhip çerçevesi ve kenar süsü çizer."""
    canvas.saveState()
    w, h = doc.pagesize

    # Antik parşömen arka planı
    canvas.setFillColor(HexColor("#faf6ee"))
    canvas.rect(0, 0, w, h, fill=1, stroke=0)

    # Dış kalın altın çerçeve
    canvas.setStrokeColor(C_GOLD)
    canvas.setLineWidth(2.2)
    canvas.rect(12 * mm, 12 * mm, w - 24 * mm, h - 24 * mm)

    # İç ince süs çerçevesi
    canvas.setStrokeColor(C_BORDER)
    canvas.setLineWidth(0.8)
    canvas.rect(14.5 * mm, 14.5 * mm, w - 29 * mm, h - 29 * mm)

    # Dört köşe tezhip süslemeleri (Selçuklu sekizgen ve çember motifi)
    corners = [
        (14.5 * mm, 14.5 * mm),
        (w - 14.5 * mm, 14.5 * mm),
        (14.5 * mm, h - 14.5 * mm),
        (w - 14.5 * mm, h - 14.5 * mm),
    ]
    for x, y in corners:
        canvas.setStrokeColor(C_GOLD)
        canvas.setLineWidth(1.6)
        canvas.circle(x, y, 3.5 * mm, stroke=1, fill=0)
        canvas.setStrokeColor(C_TURQUOISE)
        canvas.setLineWidth(0.8)
        canvas.circle(x, y, 1.8 * mm, stroke=1, fill=0)

    # Sayfa ve alt bilgi (Türkçe font destekli)
    canvas.setFont(_ACTIVE_FONT, 8)
    canvas.setFillColor(C_MUTED)
    footer_text = f"Tabîb Ekmeleddin'in Kazanı · ERÜ Anadolu Tıp Tarihi Kulübü Gürgen Ekibi — Sayfa {doc.page}"
    canvas.drawCentredString(w / 2.0, 7 * mm, footer_text)

    canvas.restoreState()


def build_pdf() -> Path:
    global _ACTIVE_FONT
    font_name = register_fonts()
    _ACTIVE_FONT = font_name
    font_bold = f"{font_name}-Bold" if f"{font_name}-Bold" in pdfmetrics.getRegisteredFontNames() else font_name

    OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    styles = getSampleStyleSheet()

    s_top_kicker = ParagraphStyle(
        "TopKicker",
        fontName=font_bold,
        fontSize=8.5,
        leading=11,
        textColor=C_TURQUOISE,
        alignment=1,
        spaceAfter=2 * mm,
    )

    s_title = ParagraphStyle(
        "MainTitle",
        fontName=font_bold,
        fontSize=15.5,
        leading=19,
        textColor=C_GOLD,
        alignment=1,
        spaceAfter=2 * mm,
    )

    s_subtitle = ParagraphStyle(
        "SubTitle",
        fontName=font_name,
        fontSize=9.5,
        leading=13,
        textColor=C_MUTED,
        alignment=1,
        spaceAfter=3 * mm,
    )

    s_section = ParagraphStyle(
        "SectionHeader",
        fontName=font_bold,
        fontSize=10.5,
        leading=14,
        textColor=C_TURQUOISE,
        spaceBefore=3 * mm,
        spaceAfter=1.5 * mm,
    )

    s_subsection = ParagraphStyle(
        "SubSectionHeader",
        fontName=font_bold,
        fontSize=9,
        leading=12,
        textColor=HexColor("#8a4b12"),
        spaceBefore=1.5 * mm,
        spaceAfter=1 * mm,
    )

    s_body = ParagraphStyle(
        "Body",
        fontName=font_name,
        fontSize=8.5,
        leading=12.5,
        textColor=C_INK,
        spaceAfter=2 * mm,
        alignment=4,  # Justified
    )

    s_quote = ParagraphStyle(
        "Quote",
        fontName=font_name,
        fontSize=8.5,
        leading=12.5,
        textColor=HexColor("#4a3622"),
        leftIndent=6 * mm,
        rightIndent=6 * mm,
        spaceBefore=2 * mm,
        spaceAfter=2 * mm,
    )

    story = []

    # ══════════════════════════════════════════════════════════════════════════
    # SAYFA 1: BAŞLIK, BİYOGRAFİ & KLİNİK SEMİYOLOJİ (TEŞHİS METODLARI)
    # ══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("ANADOLU SELÇUKLU KLİNİK TIP TARİHİ · AKADEMİK VE HEKİMLİK MONOGRAFİSİ", s_top_kicker))
    story.append(Paragraph("TABÎB EKMELEDDİN (BEY HEKİM) VE 13. YY. KLİNİK TIP DOKTRİNİ", s_title))
    story.append(Paragraph("Klinik Semiyoloji, Sfigmoloji, Galenik Farmakoloji ve Selçuklu Dârüşşifası Tıp Pratiği", s_subtitle))
    story.append(HRFlowable(width="95%", thickness=1.0, color=C_GOLD, spaceBefore=1 * mm, spaceAfter=2.5 * mm))

    # Bölüm 1: Biyografik Arka Plan ve Ekol
    story.append(Paragraph("1. Tarihî Kimliği, Tıbbî Formasyonu ve Selçuklu Saray Riyaseti", s_section))
    story.append(Paragraph(
        "Asıl künyesi <b>Ekmeleddîn Tabîb el-Nahcivânî</b> olan ve tıp mahareti sebebiyle hem Selçuklu sarayında "
        "hem de halk nezdinde hürmetle <b>Bey Hekim</b> (Melikü'l-Hükemâ / Reisü'l-Etıbbâ) unvanıyla anılan usta hekim, "
        "13. yüzyılda Anadolu Selçuklu Devleti'nin başkenti Konya'da tıp ilminin zirvesini temsil etmiştir. "
        "Sultan II. İzzeddin Keykavus ve IV. Rükneddin Kılıçarslan devirlerinde saray baştabipliği görevini üstlenmiş; "
        "Konya Dârüşşifası'nın ve ordu sıhhiyesinin idaresini yürütmüştür. İbn Sînâ'nın <i>El-Kânûn fî't-Tıbb</i> ve "
        "Ebû Bekir er-Râzî'nin <i>Kitâbü'l-Hâvî</i> ekollerindeki rasyonel, ampirik ve klinik gözleme dayalı tanı geleneğini "
        "Anadolu coğrafyasında kurumsallaştırmış; Konya'da günümüze ulaşan tarihî <b>Beyhekim Mescidi</b> ve dârüşşifa "
        "külliyesini inşa ettirerek hekimlik namzetlerine bizzat yatak başında (bedside medicine) klinik eğitim vermiştir.",
        s_body
    ))

    # Bölüm 2: Klinik Semiyoloji ve Tanı Metodolojisi
    story.append(Paragraph("2. Klinik Semiyoloji ve İleri Teşhis Metodolojisi (İlm-i Teşhis)", s_section))
    story.append(Paragraph(
        "Tabîb Ekmeleddin'in hekimlik yaklaşımı, modern tıptaki fizik muayene ve semiyoloji prensipleriyle büyük paralellik "
        "gösteren çok katmanlı bir teşhis algoritmasına dayanmaktaydı:",
        s_body
    ))

    story.append(Paragraph("A. İlm-i Nabz (Klinik Sfigmoloji / Arteriyel Nabız Analizi):", s_subsection))
    story.append(Paragraph(
        "Tabîb Ekmeleddin, <i>arteria radialis</i> palpasyonunu yalnızca bir nabız sayımı değil, kardiyovasküler sistemin, "
        "vasküler tonusun ve iç organlardaki hemodinamik disfonksiyonların birincil göstergesi olarak kullanmıştır. "
        "Nabzı 10 majör parametre üzerinden değerlendirirdi: <b>Sür'at</b> (frekans/dakika atımı), <b>Tevatür</b> (ritim simetrisi ve aritmiler), "
        "<b>Kuvvet</b> (vuruş amplitüdü), <b>İmtilâ</b> (arteriyel gerim ve dolgunluk), <b>Salâbet</b> (damar duvarı elastikiyeti ve sertliği).<br/>"
        "• <i>Nabz-ı Müşirî (Dikrotik Nabız):</i> Vasküler direncin düştüğü septik durumlar ve aort kapak yetmezliklerinde tanımlanmıştır.<br/>"
        "• <i>Pulsus Serratus (Testere Dişi Nabız):</i> Akut hummiyat (akut febril enfeksiyonlar) ve bakteriyel toksikasyon tablolarında tespit edilmiştir.<br/>"
        "• <i>Pulsus Filiformis (İpliksi/Filiform Nabız):</i> Hipovolemi, masif kan kaybı ve vazomotor kollaps (şok) göstergesi olarak kaydedilmiştir.",
        s_body
    ))

    story.append(Paragraph("B. İlm-i Karûre (Klinik Uroskopi ve Biyokimyasal Gözlem):", s_subsection))
    story.append(Paragraph(
        "İdrar muayenesinde sabah aç karna alınan orta akım numunesi şeffaf cam fanuslarda (karûre) incelenirdi. "
        "Değerlendirmede 7 tanısal kriter esas alınırdı: <b>Renk Spektrumu</b> (ashab/sarı, ahmar/kırmızı, esved/koyu — sarılık, "
        "hematüri ve hemoglobinüri ayrımı), <b>Dansite ve Kıvam</b> (proteinüri ve osmolarite göstergesi), <b>Şeffaflık</b>, "
        "<b>Köpürme Nitelikleri</b> (safra asitleri ve nefrotik sendrom düşündüren inatçı mikroköpükler) ve <b>Rusûb (Sedimantasyon)</b> "
        "(kalsiyum oksalat/ürat kristalleriyle seyreden nefrolitiyazis ve pyüri/lökositüri ayrımı).",
        s_body
    ))

    story.append(Paragraph("C. Humoral Patoloji ve Mizaç Dengesi (Homeostaz Kuramı):", s_subsection))
    story.append(Paragraph(
        "Klasik <i>Ahlat-ı Erba'a</i> (Dört Sıvı: Kan/Dem, Balgam, Sarı Safra, Kara Safra/Sevda) doktrinini hücresel ve metabolik "
        "bir homeostaz dengesi olarak yorumlamıştır. Vücut sıvılarındaki biyokimyasal bozulmayı (<i>dyscrasia</i>) akut inflamasyon "
        "ve lokal doku nekrozunun kaynağı kabul etmiş; tedavide temel amacı immün mekanizmaları (<i>kuvvet-i müdebbire</i>) aktive "
        "ederek iç dengeyi yeniden tesis etmek olarak belirlemiştir.",
        s_body
    ))

    # Sayfa sonu geçişi
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # SAYFA 2: FARMAKOLOJİ, NÖROPSİKİYATRİ, HASTANE TRİYAJI & DEONTOLOJİ
    # ══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("3. Terkîb-i Edviye, Galenik Farmakoloji ve Tıbbi Kimya", s_section))
    story.append(Paragraph(
        "Tabîb Ekmeleddin, Selçuklu dârüşşifa eczanesinde (<i>saydalan</i>) majistral ilaç hazırlama sanatının büyük bir üstadıydı. "
        "İlaç tertibinde <b>Müfredât</b> (tekil etken maddeler) ve <b>Mürekkebât</b> (kompleks farmasötik terkipler) sistematiğini uygulamıştır:",
        s_body
    ))

    story.append(Paragraph(
        "<b>• Farmakodinamik Derecelendirme:</b> Drogları etki güçlerine göre 1. dereceden (fizyolojik destekleyiciler) 4. dereceye "
        "(yüksek toksisiteye sahip kuvvetli ajanlar) kadar sınıflandırmış; dar terapötik indekse sahip maddeleri kesin dozimetriyle kullanmıştır.<br/>"
        "<b>• Sekencebîn (Oxymel) Terapisi:</b> Sirke (asit) ve süzme bal (glukoz/antioksidan) matriksinden hazırlanan bu solüsyon, "
        "asit-baz dengesini regüle eden, hepatobilier sekresyonu artıran ve elektrolit kaybını önleyen bir hidrasyon ajanıydı.<br/>"
        "<b>• Tiryâk-ı Kebîr (Polifarmasi Panzehir):</b> 60'tan fazla drog içeren, içerisinde mürver, afyon, centiyana, zencefil ve kükürt "
        "fraksiyonları barındıran; septik tablolarda, zehirlenmelerde ve immünsüpresif tükenişlerde kullanılan kombine bir formülasyondu.<br/>"
        "<b>• İmbik ile Distilasyon ve Ekstraksiyon:</b> Uçucu yağların ve alkolik tentürlerin elde edilmesinde imbik damıtmasını "
        "kullanarak etken maddelerin saflaştırılmasını ve biyoyararlanımının artırılmasını sağlamıştır.",
        s_body
    ))

    story.append(Paragraph("4. Nöropsikiyatri, Müzikoterapi ve Hz. Mevlânâ ile Psikosomatik Yaklaşım", s_section))
    story.append(Paragraph(
        "Tabîb Ekmeleddin, psikosomatik hastalıkların ve nöropsikiyatrik tabloların (mâlihulyâ/melankoli, mania, anksiyete ve somatoform bozukluklar) "
        "tedavisinde çağının yüzyıllarca ilerisinde bir nörobilişsel vizyon sergilemiştir. Ahmed Eflâkî'nin <i>Menâkıbü'l-Ârifîn</i> eserinde "
        "belgelendiği üzere Hz. Mevlânâ'nın özel hekimi ve sırdaşı olan Bey Hekim, keder ve duygusal dalgalanmaların otonom sinir sistemi ve "
        "vasküler direnç üzerindeki yıkıcı etkilerini yakından gözlemlemiştir.",
        s_body
    ))
    story.append(Paragraph(
        "Selçuklu Dârüşşifası'nda makamların otonom sinir sistemi üzerindeki farmakomimetik sedatif/stimülan etkilerini klinik olarak reçetelendirmiştir:<br/>"
        "• <b>Rast Makamı:</b> Motor innervasyonu uyarıcı, parapleji ve spastik kas spazmlarında kas tonusunu düzenleyici.<br/>"
        "• <b>Nihavend Makamı:</b> Hipertansiyon, kardiyak aritmi ve vasküler hiperaktivitede belirgin sedatif ve tansiyon regüle edici.<br/>"
        "• <b>Rehavî Makamı:</b> Kronik sefalji (gerilim ve migren tipi baş ağrıları) ile dirençli uykusuzlukta (insomnia) analjezik tesir.<br/>"
        "• <b>Hicaz Makamı:</b> Sempatik deşarjı baskılayan, ürogenital spazmları ve panik benzeri göğüs darlıklarını teskin edici.",
        s_body
    ))
    story.append(Paragraph(
        "<i>«Mevlânâ'nın terminal dönemdeki febril tablosunda başucunda nabzını tutan Tabîb Ekmeleddin, hekimlik çaresizliğinin ve "
        "metafizik teslimiyetin sınırlarını Hz. Mevlânâ ile paylaşmış; hekim-hasta ilişkisini salt biyolojik bir mekanizmadan "
        "yüksek bir ahlaki ve felsefi tesanüde taşımıştır.»</i>",
        s_quote
    ))

    story.append(Paragraph("5. Dârüşşifa Mimarisi, Triyaj ve Hastane Enfeksiyon Kontrolü", s_section))
    story.append(Paragraph(
        "Selçuklu tıp kurumları günümüz modern hastane triyaj ve enfeksiyon kontrol standartlarının tarihsel öncüsüdür. "
        "Konya Dârüşşifası'nda açık avlulu ve çapraz hava koridorlu mimari sayesinde solunum yolu patojenlerinin seyreltilmesi sağlanmış; "
        "akut ateşli hastalar, cerrahi vakalar ve akıl hastaları (<i>bimarhane</i>) ayrı koğuşlarda tecrit (izolasyon) edilmiştir. "
        "Cerrahi müdahalelerde koterizasyon, flebotomi (venöz dekompresyon) ve antiseptik olarak gümüş suyu, kükürt ve şap solüsyonları kullanılmıştır.",
        s_body
    ))

    story.append(Paragraph("6. Tıbbî Deontoloji ve Hekimlik Ahlakı", s_section))
    story.append(Paragraph(
        "<i>«Tıbbın gayesi, yalnız uzvun marazını gidermek değil; hastanın zihnini, mizacını ve yaşama şevkini ihya etmektir. "
        "Şefkatsiz, tefekkürsüz ve tekebbür dolu bir hekimin sunduğu ilaç, devadan ziyade dert üretir.»</i> düsturunu şiar edinen "
        "Tabîb Ekmeleddin, varsıl hastalardan aldığı ücreti yoksulların dermanına vakfederek sosyal hekimliğin en asil örneğini vermiştir.",
        s_quote
    ))

    story.append(Spacer(1, 2 * mm))
    story.append(HRFlowable(width="100%", thickness=0.8, color=C_GOLD_LT, spaceBefore=1 * mm, spaceAfter=2 * mm))
    story.append(Paragraph(
        "<b>ERÜ Anadolu Tıp Tarihi Topluluğu</b> · Bu akademik vesika, tıp fakültesi hekim namzetleri ve hekimlerimiz için "
        "Anadolu Selçuklu Başhekimi Tabîb Ekmeleddin'in (Bey Hekim) klinik mirasını bilimsel tıp tarihi perspektifiyle belgelemek üzere hazırlanmıştır.",
        ParagraphStyle("Footnote", fontName=font_name, fontSize=7.5, leading=10.5, textColor=C_MUTED, alignment=1)
    ))

    doc.build(story, onFirstPage=draw_background_and_border, onLaterPages=draw_background_and_border)
    return OUTPUT_PDF


if __name__ == "__main__":
    pdf_path = build_pdf()
    print(f"Tabîb Ekmeleddin PDF başarıyla üretildi: {pdf_path} ({os.path.getsize(pdf_path)} bayt)")

