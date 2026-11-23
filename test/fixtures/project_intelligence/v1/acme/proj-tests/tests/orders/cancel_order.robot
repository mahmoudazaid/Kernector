*** Settings ***
Resource    ../../resources/orders.resource

*** Test Cases ***
Cancel Unpaid Order
    [Tags]    PROJ-123    PROJ-140
    Create Unpaid Order
    Cancel Order
    Order Should Be Cancelled
