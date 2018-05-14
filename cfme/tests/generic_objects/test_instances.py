# -*- coding: utf-8 -*-

import fauxfactory
import pytest

import cfme.rest.gen_data as rest_gen_data
from cfme import test_requirements
from cfme.base.login import BaseLoggedInPage
from cfme.services.myservice import MyService
from cfme.utils.appliance import ViaREST, ViaUI
from cfme.utils.appliance.implementations.ui import navigate_to
from cfme.utils.rest import assert_response
from cfme.utils.update import update


pytestmark = [
    test_requirements.generic_objects,
    pytest.mark.uncollectif(lambda appliance: appliance.version < "5.9",
                            reason="5.8 appliance doesn't support generic objects")
]


@pytest.fixture
def definition(appliance):
    with appliance.context.use(ViaREST):
        definition = appliance.collections.generic_object_definitions.create(
            name='rest_generic_class{}'.format(fauxfactory.gen_alphanumeric()),
            description='Generic Object Definition',
            attributes={'addr01': 'string'},
            associations={'services': 'Service'},
            methods=['add_vm', 'remove_vm']
        )
        yield definition
        if definition.exists:
            definition.delete()


@pytest.fixture
def service(appliance):
    service_name = 'rest_service_{}'.format(fauxfactory.gen_alphanumeric())
    rest_service = appliance.rest_api.collections.services.action.create(
        name=service_name,
        display=True
    )
    rest_service = rest_service[0]
    yield rest_service
    rest_service.action.delete()


@pytest.fixture
def generic_object(definition, service, appliance):
    myservice = MyService(appliance, name=service.name)
    with appliance.context.use(ViaREST):
        instance = appliance.collections.generic_objects.create(
            name='rest_generic_instance{}'.format(fauxfactory.gen_alphanumeric()),
            definition=definition,
            attributes={'addr01': 'Test Address'},
            associations={'services': [myservice]}
        )
        yield instance
        if instance.exists:
            instance.delete()


@pytest.fixture
def add_generic_object_to_service(appliance, service, generic_object):
    with appliance.context.use(ViaREST):
        service.action.add_resource(
            resource=appliance.rest_api.collections.generic_objects.find_by(
                name=generic_object.name)[0]._ref_repr()
        )
        assert_response(appliance)


@pytest.fixture(scope="module")
def categories(request, appliance):
    return rest_gen_data.categories(request, appliance.rest_api, 3)


@pytest.fixture(scope="module")
def tags(request, appliance, categories):
    return rest_gen_data.tags(request, appliance.rest_api, categories)


@pytest.fixture
def generic_object_button_group(appliance, definition):
    with appliance.context.use(ViaUI):
        group_name = 'button_group_{}'.format(fauxfactory.gen_alphanumeric())
        generic_object_button_group = definition.collections.generic_object_groups_buttons.create(
            name=group_name,
            description='Group_button_description',
            image='fa-user'
        )
        view = appliance.browser.create_view(BaseLoggedInPage)
        view.flash.assert_no_error()
        return generic_object_button_group


@pytest.fixture
def generic_object_button(appliance, generic_object_button_group, definition):

    def _generic_object_button(button_group):
        with appliance.context.use(ViaUI):
            button_parent = generic_object_button_group if button_group else definition
            button_name = 'button_{}'.format(fauxfactory.gen_alphanumeric())
            generic_object_button = button_parent.collections.generic_object_buttons.create(
                name=button_name,
                description='Button_description',
                image='fa-home',
                request=fauxfactory.gen_alphanumeric()
            )
            view = appliance.browser.create_view(BaseLoggedInPage)
            view.flash.assert_no_error()
        return generic_object_button
    return _generic_object_button


@pytest.mark.sauce
@pytest.mark.parametrize('context', [ViaREST, ViaUI])
def test_generic_objects_crud(appliance, context, request):
    with appliance.context.use(context):
        definition = appliance.collections.generic_object_definitions.create(
            name='rest_generic_class{}'.format(fauxfactory.gen_alphanumeric()),
            description='Generic Object Definition',
            attributes={'addr01': 'string'},
            associations={'services': 'Service'}
        )
        assert definition.exists
        request.addfinalizer(definition.delete)

    with appliance.context.use(ViaREST):
        myservices = []
        for _ in range(2):
            service_name = 'rest_service_{}'.format(fauxfactory.gen_alphanumeric())
            rest_service = appliance.rest_api.collections.services.action.create(
                name=service_name,
                display=True
            )
            rest_service = rest_service[0]
            request.addfinalizer(rest_service.action.delete)
            myservices.append(MyService(appliance, name=service_name))
        instance = appliance.collections.generic_objects.create(
            name='rest_generic_instance{}'.format(fauxfactory.gen_alphanumeric()),
            definition=definition,
            attributes={'addr01': 'Test Address'},
            associations={'services': [myservices[0]]}
        )
        request.addfinalizer(instance.delete)
    with appliance.context.use(context):
        assert instance.exists

    with appliance.context.use(ViaREST):
        with update(instance):
            instance.attributes = {'addr01': 'Changed'}
            instance.associations = {'services': myservices}
        rest_instance = appliance.rest_api.collections.generic_objects.get(name=instance.name)
        rest_data = appliance.rest_api.get('{}?associations=services'.format(rest_instance.href))
        assert len(rest_data['services']) == 2
        assert rest_data['property_attributes']['addr01'] == 'Changed'
        instance.delete()

    with appliance.context.use(context):
        assert not instance.exists


@pytest.mark.parametrize('button_group', [True, False],
                         ids=['button_group_with_button', 'single_button'])
@pytest.mark.parametrize('context', [ViaUI])
def test_generic_objects_with_buttons_ui(appliance, request, definition, context, service,
                                         button_group, generic_object_button_group,
                                         generic_object_button):
    """
        Tests buttons ui visibility assigned to generic object

        Metadata:
            test_flag: ui
    """
    myservice = MyService(appliance, name=service.name)
    generic_button = generic_object_button(button_group)

    with appliance.context.use(ViaREST):
        instance = appliance.collections.generic_objects.create(
            name='rest_generic_instance{}'.format(fauxfactory.gen_alphanumeric()),
            definition=definition,
            attributes={'addr01': 'Test Address'},
            associations={'services': [myservice]}
        )
        request.addfinalizer(instance.delete)
        service.action.add_resource(
            resource=appliance.rest_api.collections.generic_objects.find_by(
                name=instance.name)[0]._ref_repr()
        )
        assert_response(appliance)
        instance.my_service = myservice
    with appliance.context.use(context):
        view = navigate_to(instance, 'MyServiceDetails')
        if button_group:
            assert view.toolbar.group(generic_object_button_group.name).custom_button.has_item(
                generic_button.name)
        else:
            assert view.toolbar.button(generic_button.name).custom_button.is_displayed


@pytest.mark.parametrize('tag_place', [True, False], ids=['details', 'collection'])
@pytest.mark.parametrize('context', [ViaUI])
def test_generic_objects_tag_ui(appliance, context, generic_object, tag_place):
    """Tests assigning and unassigning tags using UI.

        Metadata:
            test_flag: ui
        """
    with appliance.context.use(context):
        assigned_tag = generic_object.add_tag(details=tag_place)
        # TODO uncomment when tags aria added to details
        # tag_available = instance.get_tags()
        # assert any(tag.category.display_name == assigned_tag.category.display_name and
        #            tag.display_name == assigned_tag.display_name
        #            for tag in tag_available), 'Assigned tag was not found on the details page'
        generic_object.remove_tag(assigned_tag, details=tag_place)
        # TODO uncomment when tags aria added to details
        # assert not(tag.category.display_name == assigned_tag.category.display_name and
        #            tag.display_name == assigned_tag.display_name
        #            for tag in tag_available), 'Assigned tag was not removed from the details page'


@pytest.mark.parametrize('context', [ViaREST])
def test_generic_objects_tag(appliance, context, generic_object, tags):
    """Tests assigning and unassigning tags using REST.

    Metadata:
        test_flag: rest
    """
    tag = tags[0]
    with appliance.context.use(context):
        generic_object.add_tag(tag)
        tag_available = generic_object.get_tags()
        assert tag.id in [t.id for t in tag_available], 'Assigned tag was not found'
        generic_object.remove_tag(tag)
        tag_available = generic_object.get_tags()
        assert tag.id not in [t.id for t in tag_available]
