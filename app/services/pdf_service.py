from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from io import BytesIO
import os
from pathlib import Path
from app.schemas.student import CertificateData, CompleteAcademicRecord

def generate_certificate_pdf(data: CertificateData) -> BytesIO:
    """Generate single semester certificate PDF."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch, leftMargin=0.5*inch, rightMargin=0.5*inch)
    elements = []
    styles = getSampleStyleSheet()

    # --- Header ---
    header_style = ParagraphStyle(
        'Header',
        parent=styles['Normal'],
        fontSize=12,
        leading=16,
        alignment=1, # Center
        fontName='Helvetica-Bold'
    )
    
    # Try to load logo from env or default path
    default_logo = Path(__file__).resolve().parent.parent / "assets" / "uit_logo.png"
    logo_path = os.getenv("CERT_LOGO_PATH", str(default_logo))
    logo_img = None
    try:
        if os.path.exists(logo_path):
            logo_img = Image(logo_path, width=1.4*inch, height=1.4*inch)
    except Exception:
        logo_img = None
    
    header_text = """
    REPUBLIC OF THE UNION OF MYANMAR<br/>
    MINISTRY OF SCIENCE AND TECHNOLOGY<br/>
    <font size=14>UNIVERSITY OF INFORMATION TECHNOLOGY</font><br/>
    Universities' Hlaing Campus, Ward (12), Parami Road,<br/>
    Hlaing Township, P.O. 11051, Yangon, Myanmar.
    """
    if logo_img:
        header_table = Table([[logo_img, Paragraph(header_text, header_style)]], colWidths=[1.6*inch, 5.9*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (0,0), (0,0), 'LEFT'),
            ('ALIGN', (1,0), (1,0), 'CENTER'),
        ]))
        elements.append(header_table)
    else:
        elements.append(Paragraph(header_text, header_style))
    elements.append(Spacer(1, 0.2*inch))
    
    contact_style = ParagraphStyle(
        'Contact',
        parent=styles['Normal'],
        fontSize=10,
        alignment=2 # Right
    )
    contact_text = """
    Phone no. : +951-9664254, +959-775 994 221<br/>
    Fax no.   : +951-9664250
    """
    elements.append(Paragraph(contact_text, contact_style))
    
    elements.append(Paragraph("<b><u>GRADING CERTIFICATE</u></b>", header_style))
    elements.append(Spacer(1, 0.2*inch))

    # --- Student Info ---
    info_style = ParagraphStyle(
        'Info',
        parent=styles['Normal'],
        fontSize=11,
        leading=14
    )
    
    info_data = [
        ["Name", f": {data.student.name} (N.R.C {data.student.nrc})"],
        ["Sex", f": {data.student.sex}"],
        ["Date of Birth", f": {data.student.dob}"],
        ["Period", f": {data.period}"]
    ]
    info_table = Table(info_data, colWidths=[1.5*inch, 5*inch])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTNAME', (1,0), (1,-1), 'Helvetica'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 0.1*inch))
    
    grading_system_text = """
    <b>Grading System</b> : A+: ≥90, A: 89~80, A-: 79~75, B+: 74~70, B: 69~65, B-: 64~60, C+: 59~55,<br/>
    C: 54~50, D: 49~40, F: <40
    """
    elements.append(Paragraph(grading_system_text, ParagraphStyle('Grading', parent=styles['Normal'], fontSize=10)))
    elements.append(Spacer(1, 0.2*inch))

    # --- Grades Table ---
    subject_style = ParagraphStyle('Subject', parent=styles['Normal'], fontSize=10, leading=12, alignment=0)
    subject_style.wordWrap = 'CJK'
    table_data = [
        ['Academic year and subjects', 'Period in\nWeek', 'Hours per week', '', 'Credit\nUnit', 'Grade', 'Grade\nPoints\nEarned'],
        ['', '', 'Lecture', 'TDA', '', '', '']
    ]
    
    table_data.append([f"{data.semester_result.academic_year}", '', '', '', '', '', ''])
    
    for result in data.semester_result.results:
        table_data.append([
            Paragraph(result.course_title if result.course_title else result.course_code, subject_style),
            '15',
            str(result.lecture_hours) if result.lecture_hours else '2',
            str(result.tda_hours) if result.tda_hours else '2',
            str(result.credit_unit) if result.credit_unit else str(int(result.points/4.0)) if result.points else '3',
            result.grade,
            f"{result.grade_points_earned:.2f}" if result.grade_points_earned else f"{result.points:.2f}"
        ])
        
    table_data.append([
        'Total Credit Unit', '', '', '', 
        str(data.semester_result.total_credit_unit), 
        'Total\nGrade\nPoint', 
        f"{data.semester_result.total_grade_points:.2f}"
    ])
    
    table_data.append([
        '', '', '', '', '', 'GPA', f"{data.semester_result.gpa:.2f}"
    ])

    col_widths = [3.0*inch, 0.7*inch, 0.6*inch, 0.6*inch, 0.8*inch, 0.8*inch, 0.7*inch]
    
    t = Table(table_data, colWidths=col_widths)
    
    t_styles = [
        ('GRID', (0,0), (-1,-2), 1, colors.black),
        ('GRID', (-2,-1), (-1,-1), 1, colors.black),
        ('SPAN', (0,0), (0,1)),
        ('SPAN', (1,0), (1,1)),
        ('SPAN', (2,0), (3,0)),
        ('SPAN', (4,0), (4,1)),
        ('SPAN', (5,0), (5,1)),
        ('SPAN', (6,0), (6,1)),
        ('SPAN', (0,2), (6,2)),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (0,3), (0,-3), 'LEFT'),
        ('SPAN', (0,-2), (3,-2)),
        ('ALIGN', (0,-2), (3,-2), 'RIGHT'),
        ('SPAN', (0,-1), (4,-1)),
        ('ALIGN', (-2,-1), (-2,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,1), 'Helvetica-Bold'),
        ('FONTNAME', (0,2), (0,2), 'Helvetica-Bold'),
        ('FONTNAME', (-2,-2), (-1,-1), 'Helvetica-Bold'),
    ]
    
    t.setStyle(TableStyle(t_styles))
    elements.append(t)
    elements.append(Spacer(1, 0.2*inch))
    
    footer_text = "The above is a grading certificate from the original record in the Student Affairs Department,<br/>University of Information Technology."
    elements.append(Paragraph(footer_text, styles['Normal']))
    
    elements.append(Spacer(1, 0.5*inch))
    
    # Signature
    sig_data = [
        ["", "Nyon", ""],
        ["", "(Nyo Mi Thar Saw)", ""],
        ["Date: ........................", "Registrar(2)", ""],
        ["", "University of Information Technology", ""]
    ]
    sig_table = Table(sig_data, colWidths=[2.5*inch, 2.5*inch, 2.5*inch])
    sig_table.setStyle(TableStyle([
        ('ALIGN', (1,0), (1,-1), 'CENTER'),
        ('FONTNAME', (1,0), (1,0), 'Times-Italic'),
        ('FONTSIZE', (1,0), (1,0), 16),
    ]))
    elements.append(sig_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_complete_transcript_pdf(data: CompleteAcademicRecord) -> BytesIO:
    """Generate complete academic transcript with all semesters and CGPA."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch, leftMargin=0.5*inch, rightMargin=0.5*inch)
    elements = []
    styles = getSampleStyleSheet()

    # --- Header ---
    header_style = ParagraphStyle(
        'Header',
        parent=styles['Normal'],
        fontSize=12,
        leading=16,
        alignment=1,
        fontName='Helvetica-Bold'
    )
    
    # Try to load logo from env or default path
    default_logo = Path(__file__).resolve().parent.parent / "assets" / "uit_logo.png"
    logo_path = os.getenv("CERT_LOGO_PATH", str(default_logo))
    logo_img = None
    try:
        if os.path.exists(logo_path):
            logo_img = Image(logo_path, width=1.4*inch, height=1.4*inch)
    except Exception:
        logo_img = None
    
    header_text = """
    REPUBLIC OF THE UNION OF MYANMAR<br/>
    MINISTRY OF SCIENCE AND TECHNOLOGY<br/>
    <font size=14>UNIVERSITY OF INFORMATION TECHNOLOGY</font><br/>
    Universities' Hlaing Campus, Ward (12), Parami Road,<br/>
    Hlaing Township, P.O. 11051, Yangon, Myanmar.
    """
    if logo_img:
        header_table = Table([[logo_img, Paragraph(header_text, header_style)]], colWidths=[1.6*inch, 5.9*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (0,0), (0,0), 'LEFT'),
            ('ALIGN', (1,0), (1,0), 'CENTER'),
        ]))
        elements.append(header_table)
    else:
        elements.append(Paragraph(header_text, header_style))
    elements.append(Spacer(1, 0.2*inch))
    
    elements.append(Paragraph("<b><u>COMPLETE ACADEMIC TRANSCRIPT</u></b>", header_style))
    elements.append(Spacer(1, 0.2*inch))

    # --- Student Info ---
    info_style = ParagraphStyle(
        'Info',
        parent=styles['Normal'],
        fontSize=11,
        leading=14
    )
    
    info_data = [
        ["Name", f": {data.student.name} (N.R.C {data.student.nrc})"],
        ["Sex", f": {data.student.sex}"],
        ["Date of Birth", f": {data.student.dob}"],
        ["Total Credits Earned", f": {data.academic_summary.total_credits_earned}"],
        ["CGPA", f": {data.academic_summary.cgpa:.2f}"]
    ]
    info_table = Table(info_data, colWidths=[2*inch, 4.5*inch])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTNAME', (1,0), (1,-1), 'Helvetica'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 0.2*inch))
    
    grading_system_text = """
    <b>Grading System</b> : A+: ≥90, A: 89~80, A-: 79~75, B+: 74~70, B: 69~65, B-: 64~60, C+: 59~55,<br/>
    C: 54~50, D: 49~40, F: <40
    """
    elements.append(Paragraph(grading_system_text, ParagraphStyle('Grading', parent=styles['Normal'], fontSize=10)))
    elements.append(Spacer(1, 0.3*inch))

    # --- Generate table for each semester ---
    subject_style = ParagraphStyle('Subject', parent=styles['Normal'], fontSize=10, leading=12, alignment=0)
    subject_style.wordWrap = 'CJK'
    for i, semester in enumerate(data.academic_summary.semesters):
        # Semester header
        semester_title = f"<b>{semester.academic_year} - {semester.semester}</b>"
        elements.append(Paragraph(semester_title, ParagraphStyle('SemesterTitle', parent=styles['Normal'], fontSize=12, fontName='Helvetica-Bold')))
        elements.append(Spacer(1, 0.1*inch))
        
        # Semester grades table
        table_data = [
            ['Course Code', 'Course Title', 'Credits', 'Grade', 'Grade Points', 'Points Earned'],
        ]
        
        for result in semester.results:
            table_data.append([
                result.course_code,
                Paragraph(result.course_title or result.course_code, subject_style),
                str(result.credit_unit),
                result.grade,
                f"{result.points:.2f}",
                f"{result.grade_points_earned:.2f}"
            ])
        
        # Semester summary
        table_data.append([
            '', '', str(semester.total_credit_unit), '', 'Total Points:', f"{semester.total_grade_points:.2f}"
        ])
        table_data.append([
            '', '', '', '', 'Semester GPA:', f"{semester.gpa:.2f}"
        ])
        
        col_widths = [1.2*inch, 2.4*inch, 0.8*inch, 0.8*inch, 1.0*inch, 1.0*inch]
        
        t = Table(table_data, colWidths=col_widths)
        
        t_styles = [
            ('GRID', (0,0), (-1,-1), 1, colors.black),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (1,1), (1,-3), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTNAME', (-2,-2), (-1,-1), 'Helvetica-Bold'),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('BACKGROUND', (-2,-2), (-1,-1), colors.lightgrey),
        ]
        
        t.setStyle(TableStyle(t_styles))
        elements.append(t)
        
        if i < len(data.academic_summary.semesters) - 1:
            elements.append(Spacer(1, 0.3*inch))
        else:
            elements.append(Spacer(1, 0.2*inch))
    
    # Overall summary
    elements.append(Paragraph("<b>Overall Academic Summary</b>", ParagraphStyle('SummaryTitle', parent=styles['Normal'], fontSize=12, fontName='Helvetica-Bold')))
    elements.append(Spacer(1, 0.1*inch))
    
    summary_data = [
        ['Total Credits Earned', str(data.academic_summary.total_credits_earned)],
        ['Total Grade Points', f"{data.academic_summary.total_grade_points:.2f}"],
        ['Cumulative GPA (CGPA)', f"{data.academic_summary.cgpa:.2f}"]
    ]
    
    summary_table = Table(summary_data, colWidths=[2.5*inch, 1.5*inch])
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('BACKGROUND', (0,0), (-1,-1), colors.lightgrey),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 0.3*inch))
    
    footer_text = "The above is a complete academic transcript from the original record in the Student Affairs Department,<br/>University of Information Technology."
    elements.append(Paragraph(footer_text, styles['Normal']))
    
    elements.append(Spacer(1, 0.5*inch))
    
    # Signature
    sig_data = [
        ["", "Nyon", ""],
        ["", "(Nyo Mi Thar Saw)", ""],
        ["Date: ........................", "Registrar(2)", ""],
        ["", "University of Information Technology", ""]
    ]
    sig_table = Table(sig_data, colWidths=[2.5*inch, 2.5*inch, 2.5*inch])
    sig_table.setStyle(TableStyle([
        ('ALIGN', (1,0), (1,-1), 'CENTER'),
        ('FONTNAME', (1,0), (1,0), 'Times-Italic'),
        ('FONTSIZE', (1,0), (1,0), 16),
    ]))
    elements.append(sig_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer
