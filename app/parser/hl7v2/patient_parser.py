from domain.patient import PatientData


def parse_pid(pid_segment):

    patient = PatientData()

    patient.identifier = pid_segment[3]

    patient.family_name = pid_segment[5][0]

    patient.given_names = [
        pid_segment[5][1]
    ]

    patient.birth_date = pid_segment[7]

    patient.gender = pid_segment[8]

    return patient