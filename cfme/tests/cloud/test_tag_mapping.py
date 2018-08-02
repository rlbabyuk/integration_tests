import fauxfactory
import pytest
from cfme.cloud.provider.ec2 import EC2Provider
from cfme.utils.appliance.implementations.ui import navigate_to


pytestmark = [
    pytest.mark.provider([EC2Provider]),
    pytest.mark.usefixtures('setup_provider')
]


@pytest.fixture(params=['instances', 'images'])
def tag_mapping_items(request, appliance, provider):
    type = request.param
    collection = getattr(appliance.collections, 'cloud_{}'.format(type))
    collection.filters = {'provider': provider}
    view = navigate_to(collection, 'AllForProvider')
    name = view.entities.get_first_entity().name
    mgmt_item = (provider.mgmt.get_vm(name) if type == 'instances'
                 else provider.mgmt.get_template(name))
    return collection.instantiate(name=name, provider=provider), mgmt_item, type


@pytest.fixture
def tag_label():
    return 'tag_label_{}'.format(fauxfactory.gen_alphanumeric())


@pytest.fixture
def tag_value():
    return 'tag_value_{}'.format(fauxfactory.gen_alphanumeric())


def test_labels_update(provider, tag_mapping_items, tag_label, tag_value, soft_assert):
    item, mgmt_item, type = tag_mapping_items
    mgmt_item.set_tag(tag_label, tag_value)
    provider.refresh_provider_relationships(method='ui')
    view = navigate_to(item, 'Details')
    current_tag_value = view.entities.summary('Labels').get_text_of(tag_label)
    soft_assert(
        current_tag_value == tag_value, (
            'Tag values is not that expected, actual - {}, expected - {}'.format(
                current_tag_value, tag_value
            )
        )
    )
    mgmt_item.unset_tag(tag_label, tag_value)
    provider.refresh_provider_relationships(method='ui')
    view = navigate_to(item, 'Details')
    fields = view.entities.summary('Labels').fields
    soft_assert(
        tag_label not in fields,
        '{} label was not removed from details page'.format(tag_label)
    )


def test_mapping_tags(appliance, provider, tag_mapping_items, tag_label, tag_value,
                     soft_assert, category, request):
    item, mgmt_item, type = tag_mapping_items
    mgmt_item.set_tag(tag_label, tag_value)
    request.addfinalizer(lambda: mgmt_item.unset_tag(tag_label, tag_value))
    provider_type = provider.discover_name.split(' ')[0]
    view = navigate_to(appliance.collections.map_tags, 'Add')

    for option in view.resource_entity.all_options:
        if type.capitalize()[:-1] in option.text and provider_type in option.text:
            select_text = option.text
            break
    map_tag = appliance.collections.map_tags.create(
        entity_type=select_text, label=tag_label, category=category.name
    )
    provider.refresh_provider_relationships(method='ui')
    view = navigate_to(item, 'Details')
    assigned_tags = view.entities.summary('Smart Management').get_text_of('My Company Tags')
    soft_assert('{}: {}'.format(category.name, tag_value) in assigned_tags)
    map_tag.delete()
    provider.refresh_provider_relationships(method='ui')
    view = navigate_to(item, 'Details')
    assigned_tags = view.entities.summary('Smart Management').get_text_of('My Company Tags')
    soft_assert(not '{}: {}'.format(category.name, tag_value) in assigned_tags)