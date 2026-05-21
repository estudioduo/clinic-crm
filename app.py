from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, timedelta
from sqlalchemy import func
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'odonto-crm-secret-2024')

db_url = os.environ.get('DATABASE_URL', 'sqlite:///odonto.db')
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
    allergies = db.Column(db.Text)
    bruxism = db.Column(db.Boolean, default=False)  # ranger de dentes
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    appointments = db.relationship('Appointment', backref='patient', lazy=True, cascade='all, delete-orphan')
    treatments = db.relationship('Treatment', backref='patient', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='patient', lazy=True, cascade='all, delete-orphan')

    @property
    def age(self):
        if self.birth_date:
            today = date.today()
            return today.year - self.birth_date.year - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
        return None


class Dentist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    cro = db.Column(db.String(20))  # Conselho Regional de Odontologia
    specialties = db.Column(db.String(200))  # Ortodontia, Implantologia, etc
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    active = db.Column(db.Boolean, default=True)
    appointments = db.relationship('Appointment', backref='dentist', lazy=True)
    treatments = db.relationship('Treatment', backref='dentist', lazy=True)


class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    dentist_id = db.Column(db.Integer, db.ForeignKey('dentist.id'))
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    duration = db.Column(db.Integer, default=30)
    type = db.Column(db.String(50))  # Limpeza, Avaliação, Tratamento, etc
    status = db.Column(db.String(20), default='Agendado')
    reason = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def datetime_str(self):
        return f"{self.date.strftime('%d/%m/%Y')} às {self.time.strftime('%H:%M')}"


class Treatment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    dentist_id = db.Column(db.Integer, db.ForeignKey('dentist.id'))
    name = db.Column(db.String(100), nullable=False)  # Canal, Restauração, Clareamento, etc
    status = db.Column(db.String(20), default='Proposta')  # Proposta, Em andamento, Concluído, Cancelado
    start_date = db.Column(db.Date)
    estimated_end = db.Column(db.Date)
    end_date = db.Column(db.Date)
    total_cost = db.Column(db.Float)
    paid_amount = db.Column(db.Float, default=0)
    sessions_planned = db.Column(db.Integer)
    sessions_completed = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def remaining_cost(self):
        return (self.total_cost or 0) - (self.paid_amount or 0)

    @property
    def progress(self):
        if not self.sessions_planned:
            return 0
        return int((self.sessions_completed / self.sessions_planned) * 100)


class Tooth(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    tooth_number = db.Column(db.String(5), nullable=False)  # 11, 12, 13... (FDI notation)
    status = db.Column(db.String(50))  # Hígido, Cárie, Obturado, Extraído, Implante, etc
    notes = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    treatment_id = db.Column(db.Integer, db.ForeignKey('treatment.id'))
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    due_date = db.Column(db.Date)
    paid_date = db.Column(db.Date)
    method = db.Column(db.String(30))
    status = db.Column(db.String(20), default='Pendente')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    today = date.today()
    total_patients = Patient.query.count()
    today_appointments = Appointment.query.filter_by(date=today).count()
    active_treatments = Treatment.query.filter_by(status='Em andamento').count()
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
        active_treatments=active_treatments,
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
    patients_list = query.order_by(Patient.name).all()
    return render_template('patients/list.html', patients=patients_list, q=q)


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
            bruxism='bruxism' in request.form,
            allergies=request.form.get('allergies'),
            notes=request.form.get('notes'),
        )
        db.session.add(patient)
        db.session.commit()
        flash('Paciente cadastrado!', 'success')
        return redirect(url_for('patient_detail', id=patient.id))
    return render_template('patients/form.html', patient=None)


@app.route('/patients/<int:id>')
def patient_detail(id):
    patient = Patient.query.get_or_404(id)
    appointments = Appointment.query.filter_by(patient_id=id).order_by(Appointment.date.desc()).all()
    treatments = Treatment.query.filter_by(patient_id=id).order_by(Treatment.created_at.desc()).all()
    payments = Payment.query.filter_by(patient_id=id).order_by(Payment.due_date.desc()).all()
    teeth = Tooth.query.filter_by(patient_id=id).all()
    total_paid = sum(p.amount for p in payments if p.status == 'Pago')
    total_pending = sum(p.amount for p in payments if p.status == 'Pendente')
    return render_template('patients/detail.html', patient=patient,
        appointments=appointments, treatments=treatments, payments=payments, teeth=teeth,
        total_paid=total_paid, total_pending=total_pending,
        dentists=Dentist.query.filter_by(active=True).all())


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
        patient.bruxism = 'bruxism' in request.form
        patient.allergies = request.form.get('allergies')
        patient.notes = request.form.get('notes')
        db.session.commit()
        flash('Paciente atualizado!', 'success')
        return redirect(url_for('patient_detail', id=id))
    return render_template('patients/form.html', patient=patient)


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
        dentists=Dentist.query.filter_by(active=True).all())


@app.route('/appointments/new', methods=['GET', 'POST'])
def appointment_new():
    if request.method == 'POST':
        appt = Appointment(
            patient_id=int(request.form['patient_id']),
            dentist_id=int(request.form['dentist_id']) if request.form.get('dentist_id') else None,
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
        flash('Consulta agendada!', 'success')
        return redirect(url_for('appointments'))
    patient_id = request.args.get('patient_id')
    return render_template('appointments/form.html', appointment=None,
        patients=Patient.query.order_by(Patient.name).all(),
        dentists=Dentist.query.filter_by(active=True).all(),
        preselected_patient=patient_id)


@app.route('/appointments/<int:id>/edit', methods=['GET', 'POST'])
def appointment_edit(id):
    appt = Appointment.query.get_or_404(id)
    if request.method == 'POST':
        appt.patient_id = int(request.form['patient_id'])
        appt.dentist_id = int(request.form['dentist_id']) if request.form.get('dentist_id') else None
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
        dentists=Dentist.query.filter_by(active=True).all(),
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


# ─── Treatments ───────────────────────────────────────────────────────────────

@app.route('/treatments')
def treatments():
    filter_status = request.args.get('status', '')
    query = Treatment.query
    if filter_status:
        query = query.filter_by(status=filter_status)
    treatments_list = query.order_by(Treatment.created_at.desc()).all()
    return render_template('treatments/list.html', treatments=treatments_list,
        filter_status=filter_status,
        patients=Patient.query.order_by(Patient.name).all(),
        dentists=Dentist.query.filter_by(active=True).all())


@app.route('/treatments/new', methods=['POST'])
def treatment_new():
    start = request.form.get('start_date')
    estimated = request.form.get('estimated_end')
    treatment = Treatment(
        patient_id=int(request.form['patient_id']),
        dentist_id=int(request.form['dentist_id']) if request.form.get('dentist_id') else None,
        name=request.form['name'],
        status=request.form.get('status', 'Proposta'),
        start_date=datetime.strptime(start, '%Y-%m-%d').date() if start else None,
        estimated_end=datetime.strptime(estimated, '%Y-%m-%d').date() if estimated else None,
        total_cost=float(request.form.get('total_cost', 0)),
        sessions_planned=int(request.form.get('sessions_planned', 1)),
        notes=request.form.get('notes'),
    )
    db.session.add(treatment)
    db.session.commit()
    flash('Tratamento registrado!', 'success')
    return redirect(url_for('patient_detail', id=treatment.patient_id))


@app.route('/treatments/<int:id>/update', methods=['POST'])
def treatment_update(id):
    treatment = Treatment.query.get_or_404(id)
    treatment.status = request.form.get('status', treatment.status)
    treatment.sessions_completed = int(request.form.get('sessions_completed', treatment.sessions_completed))
    treatment.paid_amount = float(request.form.get('paid_amount', treatment.paid_amount))

    end = request.form.get('end_date')
    if end:
        treatment.end_date = datetime.strptime(end, '%Y-%m-%d').date()

    db.session.commit()
    flash('Tratamento atualizado!', 'success')
    return redirect(request.referrer or url_for('patient_detail', id=treatment.patient_id))


@app.route('/treatments/<int:id>/delete', methods=['POST'])
def treatment_delete(id):
    treatment = Treatment.query.get_or_404(id)
    pid = treatment.patient_id
    db.session.delete(treatment)
    db.session.commit()
    flash('Tratamento removido.', 'info')
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
    return render_template('financial/list.html', payments=payments,
        filter_status=filter_status, filter_month=filter_month,
        total_paid=total_paid, total_pending=total_pending,
        patients=Patient.query.order_by(Patient.name).all(),
        today=today)


@app.route('/financial/new', methods=['POST'])
def payment_new():
    dd = request.form.get('due_date')
    pd = request.form.get('paid_date')
    payment = Payment(
        patient_id=int(request.form['patient_id']),
        treatment_id=int(request.form['treatment_id']) if request.form.get('treatment_id') else None,
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
    flash('Cobrança registrada!', 'success')
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


# ─── Dentists ─────────────────────────────────────────────────────────────────

@app.route('/dentists')
def dentists():
    dentists_list = Dentist.query.order_by(Dentist.name).all()
    return render_template('dentists/list.html', dentists=dentists_list)


@app.route('/dentists/new', methods=['GET', 'POST'])
def dentist_new():
    if request.method == 'POST':
        dentist = Dentist(
            name=request.form['name'],
            cro=request.form.get('cro'),
            specialties=request.form.get('specialties'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
        )
        db.session.add(dentist)
        db.session.commit()
        flash('Dentista cadastrado!', 'success')
        return redirect(url_for('dentists'))
    return render_template('dentists/form.html', dentist=None)


@app.route('/dentists/<int:id>/edit', methods=['GET', 'POST'])
def dentist_edit(id):
    dentist = Dentist.query.get_or_404(id)
    if request.method == 'POST':
        dentist.name = request.form['name']
        dentist.cro = request.form.get('cro')
        dentist.specialties = request.form.get('specialties')
        dentist.phone = request.form.get('phone')
        dentist.email = request.form.get('email')
        dentist.active = 'active' in request.form
        db.session.commit()
        flash('Dentista atualizado!', 'success')
        return redirect(url_for('dentists'))
    return render_template('dentists/form.html', dentist=dentist)


@app.route('/dentists/<int:id>/delete', methods=['POST'])
def dentist_delete(id):
    dentist = Dentist.query.get_or_404(id)
    db.session.delete(dentist)
    db.session.commit()
    flash('Dentista removido.', 'info')
    return redirect(url_for('dentists'))


# ─── Calendar ─────────────────────────────────────────────────────────────────

@app.route('/calendar')
def calendar():
    return render_template('calendar.html')


@app.route('/api/appointments')
def api_appointments():
    events = []
    for a in Appointment.query.all():
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


# ─── Init ─────────────────────────────────────────────────────────────────────

def create_sample_data():
    if Patient.query.count() > 0:
        return

    dentist = Dentist(name='Dra. Ana Silva', cro='CRO-12345', specialties='Ortodontia, Implantologia',
                     phone='(11) 99999-0001', email='ana@odonto.com')
    db.session.add(dentist)
    db.session.flush()

    p1 = Patient(name='Maria Oliveira', cpf='123.456.789-00', phone='(11) 99111-2222',
                email='maria@email.com', birth_date=date(1985, 3, 15), allergies='Dipirona', bruxism=True)
    p2 = Patient(name='João Santos', cpf='987.654.321-00', phone='(11) 98222-3333',
                email='joao@email.com', birth_date=date(1972, 7, 20))
    db.session.add_all([p1, p2])
    db.session.flush()

    today = date.today()
    a1 = Appointment(patient_id=p1.id, dentist_id=dentist.id, date=today,
                    time=datetime.strptime('09:00', '%H:%M').time(),
                    type='Limpeza', status='Confirmado')
    a2 = Appointment(patient_id=p2.id, dentist_id=dentist.id, date=today,
                    time=datetime.strptime('10:30', '%H:%M').time(),
                    type='Avaliação', status='Agendado')
    db.session.add_all([a1, a2])

    t1 = Treatment(patient_id=p1.id, dentist_id=dentist.id, name='Canal Dente 36',
                  status='Em andamento', start_date=today, total_cost=800.0, sessions_planned=3, sessions_completed=1)
    db.session.add(t1)

    pay1 = Payment(patient_id=p1.id, treatment_id=t1.id, description='Primeira sessão - Canal',
                  amount=300.0, due_date=today, status='Pago', paid_date=today, method='Dinheiro')
    pay2 = Payment(patient_id=p2.id, description='Limpeza', amount=150.0, due_date=today,
                  status='Pendente', method='Cartão')
    db.session.add_all([pay1, pay2])

    # Odontograma
    for i in range(11, 49):
        tooth = Tooth(patient_id=p1.id, tooth_number=str(i), status='Hígido')
        db.session.add(tooth)

    db.session.commit()


with app.app_context():
    db.create_all()
    create_sample_data()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
