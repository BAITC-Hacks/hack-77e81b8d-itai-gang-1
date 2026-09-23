"""Fictional fixture for a UI demo, never a result of uploaded documents."""

from ui_contract import AnalysisReport


def demo_report() -> AnalysisReport:
    sources = [
        {"id": "before:p1", "document": "Положение до.docx", "version": "before",
         "location": "п. 1.1", "text": "Отдел закупок выбирает поставщиков и ведёт реестр договоров."},
        {"id": "before:p2", "document": "Положение до.docx", "version": "before",
         "location": "п. 1.2", "text": "Отдел контроля независимо проверяет закупки и согласует выбор поставщика."},
        {"id": "after:p1", "document": "Положение после.docx", "version": "after",
         "location": "п. 2.1", "text": "Департамент снабжения выбирает поставщиков и самостоятельно согласует их выбор."},
        {"id": "after:p2", "document": "Положение после.docx", "version": "after",
         "location": "п. 2.2", "text": "Административный отдел выбирает поставщиков для закупок."},
    ]
    duplicate = {"title": "Выбор поставщиков закреплён за двумя подразделениями",
                 "explanation": "Границы закупок между снабжением и административным отделом не определены.",
                 "source_ids": ["after:p1", "after:p2"]}
    conflict = {"title": "Выбор и согласование поставщика совмещены",
                "explanation": "Потенциальный конфликт интересов: снабжение согласует собственный выбор. Требуется проверка сотрудником.",
                "source_ids": ["before:p2", "after:p1"]}
    return AnalysisReport.model_validate({
        "departments": [
            {"title": "Отдел закупок → Департамент снабжения", "status": "reorganized",
             "explanation": "Функция выбора поставщиков передана снабжению; преобразование требует подтверждения распорядительным документом.",
             "source_ids": ["before:p1", "after:p1"]},
            {"title": "Административный отдел", "status": "created",
             "explanation": "Подразделение появилось в учебном комплекте «после».",
             "source_ids": ["before:p1", "before:p2", "after:p2"]},
        ],
        "functions": [
            {"title": "Ведение реестра договоров", "status": "lost",
             "before_units": ["Отдел закупок"], "after_units": [],
             "explanation": "В учебном комплекте «после» функция не найдена. Это потенциальная потеря; отсутствие нельзя доказать одним пунктом.",
             "source_ids": ["before:p1", "after:p1", "after:p2"]},
            {"title": "Выбор поставщиков", "status": "duplicated",
             "before_units": ["Отдел закупок"],
             "after_units": ["Департамент снабжения", "Административный отдел"],
             "explanation": duplicate["explanation"],
             "source_ids": ["before:p1", "after:p1", "after:p2"]},
        ],
        "duplicates": [duplicate], "conflicts": [conflict],
        "recommendations": [
            {"title": "Уточнить владельцев функций и порядок контроля",
             "explanation": "Закрепить ответственного за реестр договоров, разграничить закупки и проверить независимость согласования.",
             "source_ids": ["before:p1", "before:p2", "after:p1", "after:p2"]},
        ],
        "conclusion": {"title": "Требуется проверка распределения ответственности",
                       "explanation": "Учебный пример показывает потенциальную потерю одной функции, одно дублирование и один конфликт интересов.",
                       "source_ids": ["before:p1", "before:p2", "after:p1", "after:p2"]},
        "sources": sources,
    })
