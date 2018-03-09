import fence.resources.admin as adm
from fence.models import Group


def test_get_group(db_session, awg_users):
    info = adm.get_group_info(db_session, "test_group_2")
    assert info['name'] == 'test_group_2'
    assert info['description'] == 'the second test group'
    expected_projects = ['test_project_1', 'test_project_2']
    expected_projects.sort()
    info['projects'].sort()
    assert info['projects'] == expected_projects


def test_create_group(db_session):
    group = db_session.query(Group).filter(Group.name == 'new_group_1').first()
    assert group == None
    adm.create_group(db_session, 'new_group_1', 'a new group')
    group = db_session.query(Group).filter(Group.name == 'new_group_1').first()
    assert group.name == 'new_group_1'
    assert group.description == 'a new group'
