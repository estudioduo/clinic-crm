from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, timedelta
from sqlalchemy import func
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'clinic-crm-secret-key-2024')

# Usa PostgreSQL em produção (DATABASE_URL) e SQLite localmente
db_url = os.environ.get('DATABASE_URL', 'sqlite:///clinic.db')
# Render usa "postgres://" mas SQLAlchemy precisa de "postgresql://"
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ─── Models ───────────────────────────────────────────────────────────────────

class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    cpf = db.Column(db.String(14), unique=True)
    birth_date = db.Column(db.Date)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    address = db.Column(db.String(200))
    blood_type = db.Column(db.String(5))
    allergies = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    appointments = db.relationship('Appointment', backref='patient', lazy=True, cascade='all, delete-orphan')
    records = db.relationship('MedicalRecord', backref='patient', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='patient', lazy=True, cascade='all, delete-orphan')

    @property
    def age(self):
        if self.birth_date:
            today = date.today()
            return today.year - self.birth_date.year - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
        return None


class Doctor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    crm = db.Column(db.String(20))
    specialty = db.Column(db.String(80))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    active = db.Column(db.Boolean, default=True)
    appointments = db.relationship('Appointment', backref='doctor', lazy=True)


class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.id'))
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    duration = db.Column(db.Integer, default=30)  # minutes
    type = db.Column(db.String(50), default='Consulta')
    status = db.Column(db.String(20), default='Agendado')  # Agendado, Confirmado, Realizado, Cancelado
    reason = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def datetime_str(self):
        return f"{self.date.strftime('%d/%m/%Y')} às {self.time.strftime('%H:%M')}"


class MedicalRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.id'))
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'))
    date = db.Column(db.Date, default=date.today)
    complaint = db.Column(db.Text)
    diagnosis = db.Column(db.Text)
    prescription = db.Column(db.Text)
    exams = db.Column(db.Text)
    evolution = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    doctor_rel = db.relationship('Doctor', foreign_keys=[doctor_id])


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'))
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    due_date = db.Column(db.Date)
    paid_date = db.Column(db.Date)
    method = db.Column(db.String(30))  # Dinheiro, Cartão, Pix, Plano
    status = db.Column(db.String(20), default='Pendente')  # Pendente, Pago, Cancelado
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    today = date.today()
    total_patients = Patient.query.count()
    today_appointments = Appointment.query.filter_by(date=today).count()
    pending_payments = db.session.query(func.sum(Payment.amount)).filter_by(status='Pendente').scalar() or 0
    monthly_revenue = db.session.query(func.sum(Payment.amount)).filter(
        Payment.status == 'Pago',
        Payment.paid_date >= date(today.year, today.month, 1)
    ).scalar() or 0

    upcoming = Appointment.query.filter(
        Appointment.date >= today,
        Appointment.status.in_(['Agendado', 'Confirmado'])
    ).order_by(Appointment.date, Appointment.time).limit(5).all()

    recent_patients = Patient.query.order_by(Patient.created_at.desc()).limit(5).all()

    # Chart data: appointments last 7 days
    chart_labels = []
    chart_data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        count = Appointment.query.filter_by(date=d).count()
        chart_labels.append(d.strftime('%d/%m'))
        chart_data.append(count)

    return render_template('dashboard.html',
        total_patients=total_patients,
        today_appointments=today_appointments,
        pending_payments=pending_payments,
        monthly_revenue=monthly_revenue,
        upcoming=upcoming,
        recent_patients=recent_patients,
        chart_labels=chart_labels,
        chart_data=chart_data,
        today=today
    )


# ─── Patients ─────────────────────────────────────────────────────────────────

@app.route('/patients')
def patients():
    q = request.args.get('q', '')
    query = Patient.query
    if q:
        query = query.filter(Patient.name.ilike(f'%{q}%') | Patient.cpf.ilike(f'%{q}%'))
    patients = query.order_by(Patient.name).all()
    return render_template('patients/list.html', patients=patients, q=q)


@app.route('/patients/new', methods=['GET', 'POST'])
def patient_new():
    if request.method == 'POST':
        bd = request.form.get('birth_date')
        patient = Patient(
            name=request.form['name'],
            cpf=request.form.get('cpf'),
            birth_date=datetime.strptime(bd, '%Y-%m-%d').date() if bd else None,
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            address=request.form.get('address'),
            blood_type=request.form.get('blood_type'),
            allergies=request.form.get('allergies'),
            notes=request.form.get('notes'),
        )
        db.session.add(patient)
        db.session.commit()
        flash('Paciente cadastrado com sucesso!', 'success')
        return redirect(url_for('patient_detail', id=patient.id))
    return render_template('patients/form.html', patient=None, doctors=Doctor.query.filter_by(active=True).all())


@app.route('/patients/<int:id>')
def patient_detail(id):
    patient = Patient.query.get_or_404(id)
    appointments = Appointment.query.filter_by(patient_id=id).order_by(Appointment.date.desc()).all()
    records = MedicalRecord.query.filter_by(patient_id=id).order_by(MedicalRecord.date.desc()).all()
    payments = Payment.query.filter_by(patient_id=id).order_by(Payment.due_date.desc()).all()
    total_paid = sum(p.amount for p in payments if p.status == 'Pago')
    total_pending = sum(p.amount for p in payments if p.status == 'Pendente')
    return render_template('patients/detail.html', patient=patient,
        appointments=appointments, records=records, payments=payments,
        total_paid=total_paid, total_pending=total_pending,
        doctors=Doctor.query.filter_by(active=True).all())


@app.route('/patients/<int:id>/edit', methods=['GET', 'POST'])
def patient_edit(id):
    patient = Patient.query.get_or_404(id)
    if request.method == 'POST':
        bd = request.form.get('birth_date')
        patient.name = request.form['name']
        patient.cpf = request.form.get('cpf')
        patient.birth_date = datetime.strptime(bd, '%Y-%m-%d').date() if bd else None
        patient.phone = request.form.get('phone')
        patient.email = request.form.get('email')
        patient.address = request.form.get('address')
        patient.blood_type = request.form.get('blood_type')
        patient.allergies = request.form.get('allergies')
        patient.notes = request.form.get('notes')
        db.session.commit()
        flash('Paciente atualizado!', 'success')
        return redirect(url_for('patient_detail', id=id))
    return render_template('patients/form.html', patient=patient, doctors=Doctor.query.filter_by(active=True).all())


@app.route('/patients/<int:id>/delete', methods=['POST'])
def patient_delete(id):
    patient = Patient.query.get_or_404(id)
    db.session.delete(patient)
    db.session.commit()
    flash('Paciente removido.', 'info')
    return redirect(url_for('patients'))


# ─── Appointments ─────────────────────────────────────────────────────────────

@app.route('/appointments')
def appointments():
    today = date.today()
    filter_date = request.args.get('date', today.strftime('%Y-%m-%d'))
    filter_status = request.args.get('status', '')
    query = Appointment.query
    if filter_date:
        try:
            fd = datetime.strptime(filter_date, '%Y-%m-%d').date()
            query = query.filter_by(date=fd)
        except ValueError:
            pass
    if filter_status:
        query = query.filter_by(status=filter_status)
    appts = query.order_by(Appointment.time).all()
    return render_template('appointments/list.html', appointments=appts,
        filter_date=filter_date, filter_status=filter_status,
        patients=Patient.query.order_by(Patient.name).all(),
        doctors=Doctor.query.filter_by(active=True).all())


@app.route('/appointments/new', methods=['GET', 'POST'])
def appointment_new():
    if request.method == 'POST':
        appt = Appointment(
            patient_id=int(request.form['patient_id']),
            doctor_id=int(request.form['doctor_id']) if request.form.get('doctor_id') else None,
            date=datetime.strptime(request.form['date'], '%Y-%m-%d').date(),
            time=datetime.strptime(request.form['time'], '%H:%M').time(),
            duration=int(request.form.get('duration', 30)),
            type=request.form.get('type', 'Consulta'),
            status=request.form.get('status', 'Agendado'),
            reason=request.form.get('reason'),
            notes=request.form.get('notes'),
        )
        db.session.add(appt)
        db.session.commit()
        flash('Consulta agendada com sucesso!', 'success')
        return redirect(url_for('appointments'))
    patient_id = request.args.get('patient_id')
    return render_template('appointments/form.html', appointment=None,
        patients=Patient.query.order_by(Patient.name).all(),
        doctors=Doctor.query.filter_by(active=True).all(),
        preselected_patient=patient_id)


@app.route('/appointments/<int:id>/edit', methods=['GET', 'POST'])
def appointment_edit(id):
    appt = Appointment.query.get_or_404(id)
    if request.method == 'POST':
        appt.patient_id = int(request.form['patient_id'])
        appt.doctor_id = int(request.form['doctor_id']) if request.form.get('doctor_id') else None
        appt.date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        appt.time = datetime.strptime(request.form['time'], '%H:%M').time()
        appt.duration = int(request.form.get('duration', 30))
        appt.type = request.form.get('type', 'Consulta')
        appt.status = request.form.get('status', 'Agendado')
        appt.reason = request.form.get('reason')
        appt.notes = request.form.get('notes')
        db.session.commit()
        flash('Consulta atualizada!', 'success')
        return redirect(url_for('appointments'))
    return render_template('appointments/form.html', appointment=appt,
        patients=Patient.query.order_by(Patient.name).all(),
        doctors=Doctor.query.filter_by(active=True).all(),
        preselected_patient=None)


@app.route('/appointments/<int:id>/status', methods=['POST'])
def appointment_status(id):
    appt = Appointment.query.get_or_404(id)
    appt.status = request.form['status']
    db.session.commit()
    flash('Status atualizado!', 'success')
    return redirect(request.referrer or url_for('appointments'))


@app.route('/appointments/<int:id>/delete', methods=['POST'])
def appointment_delete(id):
    appt = Appointment.query.get_or_404(id)
    db.session.delete(appt)
    db.session.commit()
    flash('Consulta removida.', 'info')
    return redirect(url_for('appointments'))


# ─── Calendar API ─────────────────────────────────────────────────────────────

@app.route('/api/appointments')
def api_appointments():
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    query = Appointment.query
    events = []
    for a in query.all():
        color_map = {
            'Agendado': '#3b82f6',
            'Confirmado': '#10b981',
            'Realizado': '#6b7280',
            'Cancelado': '#ef4444',
        }
        events.append({
            'id': a.id,
            'title': f"{a.time.strftime('%H:%M')} - {a.patient.name}",
            'start': f"{a.date.isoformat()}T{a.time.strftime('%H:%M')}:00",
            'color': color_map.get(a.status, '#3b82f6'),
            'url': url_for('patient_detail', id=a.patient_id),
        })
    return jsonify(events)


# ─── Medical Records ──────────────────────────────────────────────────────────

@app.route('/records/new', methods=['POST'])
def record_new():
    record = MedicalRecord(
        patient_id=int(request.form['patient_id']),
        doctor_id=int(request.form['doctor_id']) if request.form.get('doctor_id') else None,
        date=datetime.strptime(request.form['date'], '%Y-%m-%d').date(),
        complaint=request.form.get('complaint'),
        diagnosis=request.form.get('diagnosis'),
        prescription=request.form.get('prescription'),
        exams=request.form.get('exams'),
        evolution=request.form.get('evolution'),
    )
    db.session.add(record)
    db.session.commit()
    flash('Prontuário salvo com sucesso!', 'success')
    return redirect(url_for('patient_detail', id=record.patient_id))


@app.route('/records/<int:id>/delete', methods=['POST'])
def record_delete(id):
    record = MedicalRecord.query.get_or_404(id)
    pid = record.patient_id
    db.session.delete(record)
    db.session.commit()
    flash('Registro removido.', 'info')
    return redirect(url_for('patient_detail', id=pid))


# ─── Financial ────────────────────────────────────────────────────────────────

@app.route('/financial')
def financial():
    today = date.today()
    filter_status = request.args.get('status', '')
    filter_month = request.args.get('month', today.strftime('%Y-%m'))
    query = Payment.query
    if filter_status:
        query = query.filter_by(status=filter_status)
    if filter_month:
        try:
            y, m = map(int, filter_month.split('-'))
            first = date(y, m, 1)
            if m == 12:
                last = date(y + 1, 1, 1) - timedelta(days=1)
            else:
                last = date(y, m + 1, 1) - timedelta(days=1)
            query = query.filter(Payment.due_date.between(first, last))
        except Exception:
            pass
    payments = query.order_by(Payment.due_date.desc()).all()
    total_paid = sum(p.amount for p in payments if p.status == 'Pago')
    total_pending = sum(p.amount for p in payments if p.status == 'Pendente')
    total_canceled = sum(p.amount for p in payments if p.status == 'Cancelado')
    return render_template('financial/list.html', payments=payments,
        filter_status=filter_status, filter_month=filter_month,
        total_paid=total_paid, total_pending=total_pending, total_canceled=total_canceled,
        patients=Patient.query.order_by(Patient.name).all(),
        today=today)


@app.route('/financial/new', methods=['POST'])
def payment_new():
    dd = request.form.get('due_date')
    pd = request.form.get('paid_date')
    payment = Payment(
        patient_id=int(request.form['patient_id']),
        description=request.form['description'],
        amount=float(request.form['amount']),
        due_date=datetime.strptime(dd, '%Y-%m-%d').date() if dd else None,
        paid_date=datetime.strptime(pd, '%Y-%m-%d').date() if pd else None,
        method=request.form.get('method'),
        status=request.form.get('status', 'Pendente'),
        notes=request.form.get('notes'),
    )
    db.session.add(payment)
    db.session.commit()
    flash('Cobrança registrada com sucesso!', 'success')
    return redirect(url_for('financial'))


@app.route('/financial/<int:id>/pay', methods=['POST'])
def payment_pay(id):
    payment = Payment.query.get_or_404(id)
    payment.status = 'Pago'
    payment.paid_date = date.today()
    payment.method = request.form.get('method', payment.method)
    db.session.commit()
    flash('Pagamento confirmado!', 'success')
    return redirect(request.referrer or url_for('financial'))


@app.route('/financial/<int:id>/delete', methods=['POST'])
def payment_delete(id):
    payment = Payment.query.get_or_404(id)
    db.session.delete(payment)
    db.session.commit()
    flash('Cobrança removida.', 'info')
    return redirect(url_for('financial'))


# ─── Doctors ──────────────────────────────────────────────────────────────────

@app.route('/doctors')
def doctors():
    doctors = Doctor.query.order_by(Doctor.name).all()
    return render_template('doctors/list.html', doctors=doctors)


@app.route('/doctors/new', methods=['GET', 'POST'])
def doctor_new():
    if request.method == 'POST':
        doctor = Doctor(
            name=request.form['name'],
            crm=request.form.get('crm'),
            specialty=request.form.get('specialty'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
        )
        db.session.add(doctor)
        db.session.commit()
        flash('Médico cadastrado!', 'success')
        return redirect(url_for('doctors'))
    return render_template('doctors/form.html', doctor=None)


@app.route('/doctors/<int:id>/edit', methods=['GET', 'POST'])
def doctor_edit(id):
    doctor = Doctor.query.get_or_404(id)
    if request.method == 'POST':
        doctor.name = request.form['name']
        doctor.crm = request.form.get('crm')
        doctor.specialty = request.form.get('specialty')
        doctor.phone = request.form.get('phone')
        doctor.email = request.form.get('email')
        doctor.active = 'active' in request.form
        db.session.commit()
        flash('Médico atualizado!', 'success')
        return redirect(url_for('doctors'))
    return render_template('doctors/form.html', doctor=doctor)


@app.route('/doctors/<int:id>/delete', methods=['POST'])
def doctor_delete(id):
    doctor = Doctor.query.get_or_404(id)
    db.session.delete(doctor)
    db.session.commit()
    flash('Médico removido.', 'info')
    return redirect(url_for('doctors'))


# ─── Calendar ─────────────────────────────────────────────────────────────────

@app.route('/calendar')
def calendar():
    return render_template('calendar.html')


# ─── Init ─────────────────────────────────────────────────────────────────────

def create_sample_data():
    if Patient.query.count() > 0:
        return
    doctor = Doctor(name='Dr. Carlos Silva', crm='CRM-12345', specialty='Clínica Geral',
                    phone='(11) 99999-0001', email='carlos@clinica.com')
    db.session.add(doctor)
    db.session.flush()

    p1 = Patient(name='Maria Oliveira', cpf='123.456.789-00', phone='(11) 99111-2222',
                 email='maria@email.com', blood_type='O+',
                 birth_date=date(1985, 3, 15), allergies='Dipirona')
    p2 = Patient(name='João Santos', cpf='987.654.321-00', phone='(11) 98222-3333',
                 email='joao@email.com', blood_type='A+',
                 birth_date=date(1972, 7, 20))
    db.session.add_all([p1, p2])
    db.session.flush()

    today = date.today()
    a1 = Appointment(patient_id=p1.id, doctor_id=doctor.id, date=today,
                     time=datetime.strptime('09:00', '%H:%M').time(),
                     type='Consulta', status='Confirmado', reason='Check-up anual')
    a2 = Appointment(patient_id=p2.id, doctor_id=doctor.id, date=today,
                     time=datetime.strptime('10:30', '%H:%M').time(),
                     type='Retorno', status='Agendado', reason='Acompanhamento')
    db.session.add_all([a1, a2])

    pay1 = Payment(patient_id=p1.id, description='Consulta - Check-up',
                   amount=250.00, due_date=today, status='Pendente', method='Pix')
    pay2 = Payment(patient_id=p2.id, description='Consulta - Retorno',
                   amount=180.00, due_date=today - timedelta(days=5),
                   paid_date=today - timedelta(days=5), status='Pago', method='Cartão')
    db.session.add_all([pay1, pay2])
    db.session.commit()


with app.app_context():
    db.create_all()
    create_sample_data()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
