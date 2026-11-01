"""DisruptionIQ frontend. Python/Reflex only; styles in assets/styles.css."""
import reflex as rx
from . import engine
from .state import State
from .webhook import carrier_api

engine.init_db()


def icon(name: str, size:int=17, color:str="#aab6ba"):
    return rx.icon(name, size=size, color=color)


def nav_entry(label:str, symbol:str, target:str):
    return rx.button(
        icon(symbol,19),rx.text(label),
        class_name=rx.cond(State.tab==target,"nav-link nav-active","nav-link"),
        on_click=State.change_tab(target),
        width="100%",justify_content="flex-start",gap="14px",variant="ghost",
    )


def top_label(text:str):
    return rx.text(text, class_name="eyebrow")


def section_title(title:str, subtitle:str=""):
    return rx.vstack(top_label(subtitle),rx.heading(title,class_name="section-title"),align_items="start",spacing="1")


def panel(*children,extra_class=""):
    return rx.box(*children,class_name=f"panel {extra_class}")


def risk_flag(score):
    return rx.badge(rx.text(score," /100"),class_name=rx.cond(score>=78,"risk-badge risk-high",rx.cond(score>=50,"risk-badge risk-mid","risk-badge risk-low")))


def action_button(label:str,event,kind:str="primary"):
    return rx.button(label,on_click=event,class_name="action-"+kind)


def login_screen():
    return rx.box(
        rx.box(class_name="login-geometry"),
        rx.center(
            rx.vstack(
                rx.hstack(
                    rx.box("N", class_name="logo-mark"),
                    rx.vstack(
                        rx.heading("NAVIPULSE", class_name="brand-display"),
                        rx.text(
                            "S U P P L Y  C H A I N  O R C H E S T R A T O R",
                            class_name="brand-strap",
                        ),
                        align_items="start",
                        spacing="0",
                    ),
                    align_items="center",
                    gap="14px",
                ),
                rx.box(height="28px"),
                top_label("SECURE OPERATIONS ACCESS // V1.0"),
                rx.vstack(
                    rx.heading("FROM SIGNAL", class_name="login-headline"),
                    rx.heading(
                        "TO RESOLUTION.",
                        class_name="login-headline login-headline-accent",
                    ),
                    class_name="login-title-stack",
                    spacing="0",
                    align_items="start",
                ),
                rx.text(
                    "Detect the cascade. Protect the SLA. Approve the response.",
                    class_name="login-subtitle",
                ),
                rx.box(height="22px"),
                rx.vstack(
                    rx.text("OPERATOR IDENTIFICATION", class_name="input-label"),
                    rx.input(
                        placeholder="username",
                        value=State.username,
                        on_change=State.set_username,
                        class_name="dark-input",
                    ),
                    rx.text("ACCESS KEY", class_name="input-label"),
                    rx.input(
                        placeholder="password",
                        value=State.password,
                        on_change=State.set_password,
                        type="password",
                        class_name="dark-input",
                    ),
                    rx.cond(
                        State.login_error != "",
                        rx.text(State.login_error, color="#ff987f", size="2"),
                    ),
                    rx.button(
                        rx.text("ACCESS CONTROL ROOM"),
                        icon("arrow-up-right", 17, "#101715"),
                        on_click=State.sign_in,
                        class_name="login-submit",
                        width="100%",
                    ),
                    rx.text(
                        "DEMO ACCOUNTS  •  analyst / manager / warehouse / procurement / admin",
                        class_name="micro",
                        text_align="center",
                    ),
                    rx.text(
                        "Credentials and role testing: see README.md",
                        class_name="micro",
                        text_align="center",
                    ),
                    spacing="3",
                    width="100%",
                    class_name="login-form",
                ),
                align_items="start",
                width="100%",
                max_width="560px",
                padding="25px",
            ),
            min_height="100vh",
            padding="30px",
        ),
        class_name="login-screen",
    )
def sidebar():
    return rx.vstack(
        rx.hstack(rx.box("D",class_name="logo-mark"),rx.vstack(
            rx.text("DISRUPTION",class_name="brand-name"),rx.text("INTELLIGENCE SYSTEM",class_name="brand-sub"),spacing="0"),
            gap="13px",align_items="center",class_name="sidebar-brand"),
        rx.text("WORKSPACE  /  01",class_name="sidebar-section"),
        nav_entry("Command center","layout-dashboard","overview"),
        nav_entry("Disruption signals","radio-tower","disruptions"),
        nav_entry("At-risk orders","package-search","orders"),
        nav_entry("Recovery studio","workflow","recovery"),
        nav_entry("Optimization lab","sigma","optimizer"),
        nav_entry("Decision approvals","shield-check","approvals"),
        rx.text("INTELLIGENCE  /  02",class_name="sidebar-section sidebar-second"),
        nav_entry("Network topology","network","network"),
        nav_entry("Data ingestion","database-zap","ingest"),
        nav_entry("Audit ledger","scroll-text","audit"),
        rx.spacer(),
        rx.vstack(
            rx.hstack(rx.box(class_name="pulse-dot"),rx.text("CONTROL ENGINE ONLINE",class_name="micro"),gap="10px"),
            rx.text("SQLite ledger + deterministic risk rules",class_name="micro muted"),
            class_name="sidebar-health",align_items="start"
        ),
        rx.hstack(
            rx.box(State.user_initial,class_name="avatar"),
            rx.vstack(rx.text(State.display_name,class_name="user-name"),rx.text(State.role,class_name="user-role"),spacing="0",align_items="start"),
            rx.spacer(),
            rx.button(icon("log-out",18),on_click=State.signout,variant="ghost",class_name="logout"),
            align_items="center",width="100%",class_name="sidebar-account"
        ),
        width="255px",min_width="255px",height="100vh",class_name="side-panel",spacing="1",align_items="stretch"
    )


def app_header():
    return rx.hstack(
        rx.vstack(top_label("OPERATIONS / LIVE OBSERVABILITY"),
                  rx.heading("NaviPulse command center.", class_name="app-head"),spacing="0",align_items="start"),
        rx.spacer(),
        rx.hstack(rx.box(class_name="pulse-dot"),rx.text("LIVE SYSTEM",class_name="micro"),class_name="header-status"),
        rx.button(icon("refresh-cw",17),"SYNC",on_click=State.refresh,class_name="outline-button"),
        class_name="top-bar",width="100%",align_items="center",gap="14px"
    )


def metric(label, value, caption, mark):
    return panel(
        rx.hstack(top_label(label),rx.spacer(),icon(mark,20,"#9eabb0"),width="100%",align_items="center"),
        rx.heading(value,class_name="stat-value"),
        rx.text(caption,class_name="stat-caption"),
        extra_class="metric-card"
    )


def signal_card(item):
    return rx.box(
        rx.hstack(
            rx.box(icon("radio",17,"#d7fd65"),class_name="signal-ico"),
            rx.vstack(rx.text(item["kind_label"],class_name="micro lime"),
                      rx.text(item["title"],class_name="item-title"),spacing="1",align_items="start"),
            rx.spacer(),risk_flag(item["max_risk"]),width="100%",align_items="center"),
        rx.text(item["detail"],class_name="muted-text"),
        rx.hstack(rx.text(item["impacted"]," ORDERS IN LINEAGE",class_name="micro"),rx.spacer(),
                  rx.button("TRACE CASCADE",icon("arrow-up-right",16),on_click=State.inspect_disruption(item["id"]),
                            class_name="text-action"),width="100%",align_items="center"),
        class_name="signal-card"
    )


def order_card(order):
    return rx.hstack(
        rx.vstack(rx.text(order["order_no"],class_name="mono-title"),rx.text(order["customer"],class_name="table-secondary"),spacing="0",width="170px",align_items="start"),
        rx.vstack(rx.text(order["sku"],class_name="table-main"),rx.text(order["warehouse"],class_name="table-secondary"),spacing="0",width="130px",align_items="start"),
        rx.vstack(rx.text(order["priority"],class_name="table-main"),rx.text(order["qty"]," UNITS",class_name="table-secondary"),spacing="0",width="90px",align_items="start"),
        rx.vstack(rx.text("$",order["value_label"],class_name="table-main"),rx.text(order["sla_short"],class_name="table-secondary"),spacing="0",width="120px",align_items="start"),
        rx.box(risk_flag(order["risk"]),width="90px"),
        rx.spacer(),
        rx.button("INSPECT",icon("arrow-up-right",14),class_name="table-button",on_click=State.inspect_order(order["id"],order["disruption_id"]),
                  disabled=order["disruption_id"]==0),
        width="100%",align_items="center",class_name="order-row",gap="10px"
    )


def order_header():
    return rx.hstack(rx.text("CUSTOMER / ORDER",width="170px"),rx.text("SKU / HUB",width="130px"),
        rx.text("PRIORITY",width="90px"),rx.text("VALUE / SLA",width="120px"),
        rx.text("RISK",width="90px"),rx.spacer(),rx.text("ACTION",width="85px"),
        width="100%",class_name="table-heading",gap="10px")


def priority_chart():
    return panel(
        rx.hstack(section_title("Risk pressure","DETERMINISTIC ORDER RANKING"),rx.spacer(),
                  rx.text("0 — 100 SCORE",class_name="micro"),align_items="center",width="100%"),
        rx.recharts.bar_chart(
            rx.recharts.cartesian_grid(stroke="#2c383c",stroke_dasharray="3 7"),
            rx.recharts.x_axis(data_key="label",stroke="#70858a",tick_line=False,axis_line=False),
            rx.recharts.y_axis(domain=[0,100],stroke="#70858a",tick_line=False,axis_line=False),
            rx.recharts.graphing_tooltip(),
            rx.recharts.bar(data_key="risk",fill="#d7fd65",radius=[4,4,0,0],bar_size=22),
            data=State.risk_bars,width="100%",height=250,
        ),extra_class="chart-card"
    )


def exposure_panel():
    return panel(
        top_label("SCENARIO LAB / FIRE A SYNTHETIC EVENT"),
        rx.heading("One alert. An entire chain.",class_name="scenario-title"),
        rx.text("See a single upstream update propagate through purchase orders, inventory availability and customer SLAs.",
                class_name="muted-text"),
        rx.vstack(
            rx.button(icon("ship",20,"#111b19"),"01  OCEAN CARRIER DELAY",icon("arrow-up-right",17,"#111b19"),
                class_name="scenario-button primary-scenario",on_click=State.run_carrier,width="100%"),
            rx.button(icon("factory",20,"#d7fd65"),"02  SUPPLIER DISRUPTION",icon("arrow-up-right",17,"#d7fd65"),
                class_name="scenario-button",on_click=State.run_supplier,width="100%"),
            rx.button(icon("package-x",20,"#d7fd65"),"03  STOCK SHORTAGE",icon("arrow-up-right",17,"#d7fd65"),
                class_name="scenario-button",on_click=State.run_stock,width="100%"),
            spacing="3",width="100%"
        ),extra_class="scenario-card"
    )


def overview():
    return rx.vstack(
        rx.hstack(
            rx.vstack(top_label("C O M M A N D   C E N T E R  /  LIVE"),
                rx.heading("Know the risk.",rx.text("Own the recovery.",color="#d7fd65"),class_name="hero-headline"),
                rx.text("From upstream disruption to customer-level action in one operating picture.",class_name="hero-sub"),
                align_items="start",spacing="2"),
            rx.spacer(),rx.box(icon("radar",62,"#d7fd65"),class_name="hero-radar"),
            class_name="hero-banner",width="100%",align_items="center"
        ),
        rx.grid(
            metric("ACTIVE DISRUPTIONS",State.summary["disruptions"],"Signals under watch","radio-tower"),
            metric("EXPOSED ORDERS",State.summary["affected"],"Unique impacted SLAs","package-search"),
            metric("PENDING CONTROL",State.summary["pending"],"Awaiting independent sign-off","shield-alert"),
            metric("RECOVERY DISPATCHES",State.summary["executing"],"Confirmed simulated actions","truck"),
            columns=rx.breakpoints(initial="1",sm="2",lg="4"),gap="13px",width="100%"
        ),
        rx.grid(priority_chart(),exposure_panel(),columns=rx.breakpoints(initial="1",lg="2"),gap="16px",width="100%"),
        rx.hstack(section_title("Disruption stream","RECENT UPSTREAM EVENTS"),rx.spacer(),
                  action_button("VIEW SIGNALS",State.change_tab("disruptions"),"secondary"),width="100%",align_items="center"),
        rx.grid(rx.foreach(State.disruptions,signal_card),columns=rx.breakpoints(initial="1",md="2"),gap="13px",width="100%"),
        rx.cond(State.disruptions.length()==0,panel(rx.text("No active alerts yet. Fire one of the scenario simulations above.",class_name="muted-text"))),
        spacing="5",width="100%",align_items="stretch"
    )


def lineage_box(label,value,iconname):
    return rx.vstack(
        rx.hstack(icon(iconname,18,"#d7fd65"),rx.text(label,class_name="micro lime"),gap="7px"),
        rx.text(value,class_name="lineage-value"),class_name="lineage-node",spacing="2",align_items="start"
    )


def lineage_record(item):
    return rx.box(
        rx.hstack(
            lineage_box("CARRIER / VESSEL",item["vessel"],"ship"),
            rx.text("→",class_name="lineage-arrow"),
            lineage_box("SHIPMENT",item["tracking"],"container"),
            rx.text("→",class_name="lineage-arrow"),
            lineage_box("PURCHASE ORDER",item["po_no"],"file-digit"),
            rx.text("→",class_name="lineage-arrow"),
            lineage_box("UPSTREAM SUPPLIER",item["supplier"],"factory"),
            rx.text("→",class_name="lineage-arrow"),
            lineage_box("WAREHOUSE INVENTORY",item["stock_label"],"warehouse"),
            rx.text("→",class_name="lineage-arrow"),
            lineage_box("PRODUCT / SKU",item["sku"],"box"),
            min_width="1230px",gap="10px",align_items="center"
        ),class_name="lineage-row"
    )


def impact_order(item):
    return rx.hstack(rx.vstack(rx.text(item["order_no"],class_name="mono-title"),rx.text(item["customer"],class_name="table-secondary"),spacing="0"),
        rx.spacer(),rx.text(item["warehouse"],class_name="micro"),
        rx.text(item["short_units"]," UNITS AT RISK",class_name="micro"),risk_flag(item["score"]),
        class_name="lineage-impact",align_items="center",width="100%",gap="15px")


def disruptions_view():
    return rx.vstack(
        rx.hstack(section_title("Signal intelligence","EVENTS / AUTOMATED LINEAGE"),rx.spacer(),
                  rx.button("FIRE CARRIER EVENT",on_click=State.run_carrier,class_name="action-primary"),width="100%",align_items="center"),
        rx.grid(rx.foreach(State.disruptions,signal_card),columns=rx.breakpoints(initial="1",md="2"),width="100%",gap="14px"),
        rx.cond(State.selected_disruption>0,
            rx.vstack(
                rx.hstack(section_title("Downstream impact trace","SQL LINEAGE • NOT A STATIC ALERT"),
                      rx.spacer(),rx.box(rx.text(State.exposure,class_name="exposure-value"),top_label("TOTAL AT-RISK CONTRACT VALUE"),
                                          class_name="exposure"),align_items="center",width="100%"),
                panel(rx.text(State.selected_disruption_info["title"],class_name="item-title"),
                      rx.text(State.selected_disruption_info["detail"],class_name="muted-text"),
                      rx.box(rx.foreach(State.lineage_nodes,lineage_record),overflow_x="auto",width="100%"),
                      rx.box(top_label("AFFECTED CUSTOMER SLAs"),rx.foreach(State.lineage_orders,impact_order),width="100%"),
                      extra_class="trace-panel"),width="100%",spacing="4",align_items="stretch"),
        ),width="100%",spacing="5",align_items="stretch"
    )


def orders_view():
    return rx.vstack(
        rx.hstack(section_title("Customer orders","PRIORITIZED BY RISK • VALUE • DEADLINE"),rx.spacer(),
                  rx.text("EXPLAINABLE SCORE  /  100",class_name="micro"),align_items="center",width="100%"),
        panel(rx.text("Rank = shortage (28) + urgency (30) + contract value (22) + SLA priority (20).",class_name="muted-text"),
              rx.box(order_header(),rx.foreach(State.orders,order_card),min_width="780px"),extra_class="table-panel"),
        width="100%",spacing="5",align_items="stretch"
    )


def recovery_option(op):
    return rx.box(
        rx.hstack(rx.box(icon("lightbulb",20,"#d7fd65"),class_name="signal-ico"),
                  rx.vstack(top_label(op["kind"]),rx.text(op["title"],class_name="option-title"),spacing="1",align_items="start"),
                  rx.spacer(),rx.text("$",op["estimate_cost"],class_name="option-cost"),align_items="center",width="100%"),
        rx.text(op["rationale"],class_name="muted-text"),
        rx.badge(op["sla_note"],class_name=rx.cond(op["meets_sla"],"risk-badge risk-low","risk-badge risk-high")),
        rx.hstack(rx.text("QTY ",op["qty"],class_name="micro"),rx.text("EST. ",op["eta_days"]," DAYS",class_name="micro"),
           rx.spacer(),rx.button("PROPOSE PLAN",icon("arrow-up-right",15),
               on_click=State.propose_option(op["kind"],op["kind_index"]),class_name="action-primary"),
            width="100%",align_items="center"),class_name="recovery-option"
    )


def recovery_view():
    return rx.vstack(
        section_title("Recovery studio","AI-ASSISTED NARRATIVE • DETERMINISTIC ACTIONS"),
        rx.cond(State.selected_order>0,
            rx.vstack(
                panel(rx.hstack(
                   rx.vstack(top_label("RECOVERY TARGET"),rx.heading(State.selected_order_info["order_no"],class_name="panel-head"),
                      rx.text(State.selected_order_info["customer"],class_name="muted-text"),align_items="start",spacing="1"),
                   rx.spacer(),risk_flag(State.selected_order_info["risk"]),align_items="center",width="100%"),
                   rx.text(State.selected_order_info["explanation"],class_name="muted-text"),extra_class="selected-order"),
                panel(rx.hstack(top_label("INTELLIGENCE / EXECUTIVE BRIEF"),rx.spacer(),
                        rx.text(State.ai_mode,class_name="micro lime"),width="100%"),
                      rx.text(State.ai_brief,class_name="brief-text"),
                      action_button("GENERATE AI BRIEF",State.ask_ai),extra_class="brief-panel"),
                rx.hstack(section_title("Validated recovery plays","ONLY FEASIBLE OPTIONS ARE GENERATED"),
                          rx.spacer(),rx.text(State.options.length()," CANDIDATES",class_name="micro"),width="100%",align_items="center"),
                rx.grid(rx.foreach(State.options,recovery_option),columns=rx.breakpoints(initial="1",md="2"),gap="14px",width="100%"),
                rx.cond(State.options.length()==0,panel(rx.text("No eligible recovery actions: current inventory and supplier constraints block these alternatives."))),
                width="100%",spacing="4",align_items="stretch"
            ),
            panel(rx.vstack(icon("mouse-pointer-click",43,"#d7fd65"),rx.heading("Begin with a customer order.",class_name="panel-head"),
                 rx.text("Open At-risk orders, then inspect any row linked to a disruption to generate recovery choices.",class_name="muted-text"),
                 action_button("VIEW AT-RISK ORDERS",State.change_tab("orders")),align_items="center",spacing="4",padding="45px"))
        ),width="100%",spacing="5",align_items="stretch"
    )


def optimization_scenario(item):
    return rx.box(
        rx.hstack(rx.text(item['profile'],class_name='micro lime'),rx.spacer(),
                  rx.text(item['orders'],' ORDERS',class_name='micro'),width='100%'),
        rx.heading('$',item['net'],class_name='option-cost'),
        rx.text('Modelled net benefit  /  ',item['sla_met'],' on-time actions',class_name='muted-text'),
        rx.hstack(rx.text('RECOVERY COST  $',item['cost'],class_name='micro'),
                  rx.spacer(),rx.text('LOSS AVOIDED  $',item['saved'],class_name='micro')),
        class_name='optimizer-scenario'
    )


def optimization_pick(item):
    return rx.box(
        rx.hstack(rx.vstack(rx.text(item['order_no'], ' / ', item['sku'], class_name='eyebrow'),
             rx.text(item['title'],class_name='option-title'),align_items='start',spacing='1'),
             rx.spacer(),rx.badge(item['kind'],class_name='status-chip'),width='100%',align_items='center'),
        rx.text(item['rationale'],class_name='muted-text'),
        rx.hstack(rx.text(item['source'],class_name='micro'),
          rx.spacer(),rx.text(item['sla_note'],class_name='micro lime'),width='100%'),
        rx.hstack(rx.text('QTY ',item['qty'],class_name='micro'),
            rx.spacer(),rx.text('COST  $',item['cost'],class_name='micro'),
            rx.text('MODELED LOSS AVOIDED  $',item['avoided_loss'],class_name='micro'),width='100%'),
        class_name='optimizer-action'
    )


def optimization_history(item):
    return rx.hstack(
        rx.vstack(rx.text('PORTFOLIO #',item['id'],' / ',item['profile'],class_name='mono-title'),
                  rx.text('Proposed by ',item['proposer'],class_name='table-secondary'),
                  align_items='start',spacing='1'),
        rx.spacer(),
        rx.text(item['executed'],' / ',item['total'],' EXECUTED',class_name='micro'),
        rx.badge(item['status'],class_name='status-chip'),
        align_items='center',width='100%',class_name='network-row')


def optimization_conflict(item):
    return rx.hstack(
        icon('git-merge',18,'#f6cd7f'),
        rx.vstack(rx.text(item['resource'],class_name='mono-title'),
              rx.text(item['contenders'],class_name='muted-text'),spacing='1',align_items='start'),
        rx.spacer(),rx.text(item['capacity'],' UNITS FREE',class_name='micro'),
        width='100%',class_name='optimizer-conflict',align_items='center'
    )


def optimization_view():
    return rx.vstack(
        rx.box(
            rx.hstack(rx.vstack(top_label('DECISION SCIENCE / INTEGER PROGRAMMING'),
                    rx.heading('Optimize the recovery.',class_name='hero-headline'),
                    rx.text('One network. Competing orders. Mathematically constrained choices.',class_name='hero-sub'),
                    align_items='start',spacing='2'),
                rx.spacer(),icon('sigma',59,'#d7fd65'),width='100%',align_items='center'),
            class_name='optimizer-hero',width='100%'),
        panel(
            section_title('What-If configuration','EXACT 0/1 OPTIMIZATION / DETERMINISTIC ENGINE'),
            rx.text('Select a trade-off, recovery budget, and total transfer capacity. The solver maximizes modeled avoided SLA loss minus recovery cost, subject to shared warehouse stock, supplier limits, exclusive shipment expedition, and one action per order.',
                    class_name='muted-text'),
            rx.grid(
                rx.vstack(rx.text('SCENARIO',class_name='input-label'),
                   rx.select(['BALANCED','SLA_FIRST','COST_FIRST'],value=State.optimizer_profile,
                        on_change=State.set_optimizer_profile,class_name='dark-input'),align_items='stretch'),
                rx.vstack(rx.text('MAX RECOVERY BUDGET ($)',class_name='input-label'),
                   rx.input(value=State.optimizer_budget_text,on_change=State.set_optimizer_budget_text,
                        class_name='dark-input'),align_items='stretch'),
                rx.vstack(rx.text('MAX TRANSFER CAPACITY (UNITS)',class_name='input-label'),
                   rx.input(value=State.optimizer_transfer_text,on_change=State.set_optimizer_transfer_text,
                        class_name='dark-input'),align_items='stretch'),
                columns=rx.breakpoints(initial='1',md='3'),gap='12px',width='100%'),
            rx.hstack(action_button('RUN WHAT-IF OPTIMIZER',State.run_optimizer),
                      rx.spacer(),rx.text('READ-ONLY SIMULATION',class_name='micro lime'),width='100%',align_items='center'),
            rx.text('SCENARIO WEIGHTS: BALANCED = 1.0x avoidance; SLA_FIRST = 2.0x (plus critical-priority weighting); COST_FIRST = 0.15x to prefer leaner decisions.',class_name='micro'),
            rx.text(State.optimizer_notice,class_name='muted-text'),
            extra_class='optimizer-config'
        ),
        rx.cond(State.optimizer_scenarios.length()>0,
            rx.vstack(
                section_title('Scenario comparison','MODELLED ECONOMICS / NOT CONTRACTUAL PENALTIES'),
                rx.grid(rx.foreach(State.optimizer_scenarios,optimization_scenario),
                        columns=rx.breakpoints(initial='1',md='3'),gap='12px',width='100%'),
                width='100%',align_items='stretch',spacing='3'
            )
        ),
        rx.grid(
            metric('ORDERS EXAMINED',State.optimizer_examined,'Impacted, eligible orders','scan-search'),
            metric('ORDERS WITH PLANS',State.optimizer_recovered,'At most one plan per order','package-check'),
            metric('ON-TIME RECOVERIES',State.optimizer_sla_met,'Based on deterministic ETAs','calendar-check'),
            metric('NET MODELLED VALUE',State.optimizer_net,'Avoided-loss proxy minus costs','scale'),
            columns=rx.breakpoints(initial='1',sm='2',lg='4'),gap='13px',width='100%'
        ),
        rx.cond(State.optimizer_conflicts.length()>0,
            panel(section_title('Shared-resource conflicts','ORDERS COMPETING FOR FINITE INVENTORY'),
                  rx.foreach(State.optimizer_conflicts,optimization_conflict),
                  extra_class='optimizer-conflicts')
        ),
        rx.hstack(section_title('Portfolio allocation','CROSS-ORDER OPTIMAL CHOICES'),
              rx.spacer(),rx.text(State.optimizer_picks.length(),' SELECTED ACTIONS',class_name='micro'),
              width='100%',align_items='center'),
        rx.grid(rx.foreach(State.optimizer_picks,optimization_pick),
            columns=rx.breakpoints(initial='1',md='2'),gap='12px',width='100%'),
        rx.cond(State.optimizer_picks.length()==0,
            panel(rx.text('Run a What-If scenario to populate the allocation. If nothing is selected, current budgets or resource constraints may be too restrictive.',class_name='muted-text'))),
        panel(rx.hstack(
            rx.vstack(top_label('COMPLIANCE GATE / NO SILENT DISPATCH'),
                rx.text('Saving a portfolio creates separate pending proposals. Supply Chain Manager and Procurement Approver review their assigned recovery types. Execution remains a separate confirmed step.',class_name='muted-text'),
                align_items='start',spacing='1'),rx.spacer(),
            rx.cond(State.optimizer_ready,
               rx.cond((State.role=='Operations Analyst') | (State.role=='Administrator'),
                   action_button('PROPOSE OPTIMIZED PORTFOLIO',State.submit_optimized_portfolio),
                   rx.text('VIEW ONLY / NOT AUTHORIZED TO PROPOSE',class_name='micro')),
               rx.text('RUN WHAT-IF FIRST',class_name='micro')),
            width='100%',align_items='center',gap='18px'),extra_class='optimizer-gate'),
        rx.cond(State.optimizer_history.length()>0,
            panel(section_title('Saved optimization portfolios','APPROVAL / EXECUTION PROGRESS'),
                rx.foreach(State.optimizer_history,optimization_history))),
        rx.text('MODELLING NOTE: 18% of at-risk contract value, weighted by impact score, is a synthetic loss proxy — not a verified SLA penalty. Scenario weights alter selection priorities only. The exact solver is deliberately bounded to 12 exposed orders.',class_name='muted-text'),
        spacing='5',width='100%',align_items='stretch'
    )


def decision_plan(item):
    return rx.box(
        rx.hstack(
            rx.vstack(top_label("RECOVERY PLAN"),rx.text("#",item["id"]," · ",item["kind"],class_name="mono-title"),spacing="0"),
            rx.spacer(),rx.badge(item["state"],class_name="status-chip"),width="100%",align_items="center"),
        rx.text(item["order_no"],"  /  ",item["rationale"],class_name="muted-text"),
        rx.hstack(rx.text("PROPOSED BY: ",item["proposed_name"],class_name="micro"),
                  rx.spacer(),rx.text("QUANTITY ",item["qty"],class_name="micro"),width="100%",align_items="center"),
        rx.cond(item['portfolio_id']>0,
            rx.text('OPTIMIZED PORTFOLIO #',item['portfolio_id'],class_name='micro lime')),
        rx.text("REQUIRED APPROVER: ", item["approver_role"], class_name="micro"),
        # Always display the backend-computed reason for missing controls.
        rx.text(item["approval_hint"], class_name="micro lime"),
        rx.cond(item["state"]=="PENDING_MANAGER_APPROVAL",
            rx.cond(item["can_decide"],
                rx.hstack(
                    rx.button("APPROVE",on_click=State.decide(item["id"],"APPROVE"),class_name="action-primary"),
                    rx.button("REJECT",on_click=State.decide(item["id"],"REJECT"),class_name="outline-button"),
                    rx.button("REQUEST CHANGES",on_click=State.decide(item["id"],"MODIFY"),class_name="outline-button"),
                    width="100%",flex_wrap="wrap",gap="8px"
                ),
                rx.box(),
            )
        ),
        rx.cond(item["state"]=="CHANGES_REQUESTED",
            rx.cond(item["can_resubmit"],
                rx.button("RESUBMIT AS PROPOSER",on_click=State.resubmit_plan(item["id"]),class_name="outline-button"),
                rx.text("Changes requested — awaiting the original proposer.",class_name="micro lime"),
            )
        ),
        rx.cond(item["state"]=="APPROVED",
            rx.cond(item["can_execute"],
                rx.button(icon("lock-keyhole-open",17),"SIMULATE EXECUTION",on_click=State.choose_execute(item["id"]),class_name="action-primary"),
                rx.cond(item["can_cancel"],
                    rx.button("CANCEL REDUNDANT PLAN",on_click=State.cancel_redundant(item["id"]),class_name="outline-button"),
                    rx.text("Execution not available; review the reason above.",class_name="micro lime"),
                ),
            )
        ),
        class_name="decision-card"
    )


def approval_view():
    return rx.vstack(
        rx.hstack(
            section_title("Dual-control approvals", "DATABASE STATE MACHINE / FOUR-EYES PRINCIPLE"),
            rx.spacer(),
            rx.button("REFRESH APPROVALS", on_click=State.refresh, class_name="outline-button"),
            align_items="center", width="100%",
        ),
        rx.text("SIGNED IN: ", State.display_name, " / ", State.role, class_name="micro lime"),
        panel(rx.hstack(icon("shield-check",28,"#d7fd65"),rx.vstack(
            rx.text("No self-approval. No silent execution.",class_name="item-title"),
            rx.text("Proposed → PENDING_MANAGER_APPROVAL → approved → explicit execution. Modifications return to the original proposer.",class_name="muted-text"),
            spacing="1",align_items="start"),gap="16px"),extra_class="control-banner"),
        rx.grid(
            panel(top_label("DECISION COMMENT / CHANGE REASON"),rx.text_area(placeholder="Why this decision or modification?",value=State.decision_note,
                   on_change=State.set_decision_note,width="100%",class_name="dark-textarea"),
                 rx.text("MODIFIED QTY — enter before requesting changes",class_name="input-label"),
                 rx.input(value=State.modify_qty,on_change=State.set_modify_qty,class_name="dark-input")),
            rx.cond(State.executing_plan_id>0,
                panel(top_label("SECOND CONTROL GATE"),
                      rx.heading("Confirm simulated dispatch?",class_name="panel-head"),
                      rx.text("No data changes until you explicitly confirm. Approval alone is not execution.",class_name="muted-text"),
                      rx.cond(State.execution_error!="",
                          rx.box(rx.text(State.execution_error,color="#ff987f",weight="medium"),
                              border="1px solid #ff987f",border_radius="8px",padding="12px",width="100%"),
                      ),
                      rx.hstack(action_button("YES, EXECUTE",State.confirm_execute),
                                action_button("CANCEL",State.cancel_execute,"secondary")),extra_class="confirm-panel"),
                panel(top_label("AUTHORIZATION POLICY"),
                      rx.text("Supply Chain Manager approves transfer, freight, and split. Procurement Approver approves alternative supplier POs.",class_name="muted-text"),
                      rx.text("Actions use authenticated server identity, never a role string from the browser.",class_name="muted-text"))
            ),columns=rx.breakpoints(initial="1",lg="2"),width="100%",gap="15px"
        ),
        rx.grid(rx.foreach(State.plans,decision_plan),columns=rx.breakpoints(initial="1",lg="2"),width="100%",gap="15px"),
        rx.cond(State.plans.length()==0,panel(rx.text("No submitted recovery plans. Select a validated recovery option first.",class_name="muted-text"))),
        width="100%",spacing="5",align_items="stretch"
    )


def network_stock(item):
    return rx.hstack(rx.vstack(rx.text(item["warehouse"],class_name="mono-title"),rx.text(item["sku"],class_name="table-secondary"),spacing="0"),
         rx.spacer(),rx.text("ON HAND ",item["on_hand"],class_name="micro"),
         rx.text("RESERVED ",item["reserved"],class_name="micro"),width="100%",align_items="center",class_name="network-row")


def network_shipment(item):
    return rx.hstack(rx.vstack(rx.text(item["tracking"],class_name="mono-title"),rx.text(item["vessel"],class_name="table-secondary"),spacing="0"),
          rx.spacer(),rx.text(item["warehouse"],class_name="micro"),rx.badge(item["status"],class_name="status-chip"),
          width="100%",align_items="center",class_name="network-row")


def fulfillment_row(item):
    return rx.hstack(rx.vstack(rx.text(item["order_no"],class_name="mono-title"),
                              rx.text(item["warehouse"]," / ",item["qty"]," units",class_name="table-secondary"),spacing="0"),
                     rx.spacer(),rx.badge(item["status"],class_name="status-chip"),
                     rx.cond(item["status"]=="PENDING",
                         rx.button("CONFIRM FULFILLMENT",on_click=State.complete_task(item["id"]),class_name="outline-button")),
                     width="100%",align_items="center",class_name="network-row")


def supplier_row(item):
    return rx.hstack(rx.text(item["name"],class_name="mono-title"),rx.spacer(),
                     rx.text("RELIABILITY ",item["reliability"],"%",class_name="micro"),
                     rx.text("DELAY ",item["delay_days"],"D",class_name="micro"),
                     width="100%",align_items="center",class_name="network-row")


def network_view():
    return rx.vstack(section_title("Network topology","WAREHOUSES / SUPPLIERS / INBOUND FREIGHT"),
        rx.grid(panel(section_title("Stock availability","PERSISTENT LOCATION RECORDS"),rx.foreach(State.inventory,network_stock)),
                panel(section_title("Inbound containers","CARRIER / PURCHASE ORDER LINKAGE"),rx.foreach(State.shipments,network_shipment)),
                columns=rx.breakpoints(initial="1",lg="2"),gap="15px",width="100%"),
        rx.grid(panel(section_title("Supplier ecosystem","ALTERNATIVES / LEAD-TIME DATA"),rx.foreach(State.suppliers,supplier_row)),
                panel(section_title("Warehouse execution queue","ONLY RESERVED SPLIT TASKS"),rx.foreach(State.tasks,fulfillment_row),
                      rx.cond(State.tasks.length()==0,rx.text("No pending dispatch tasks.",class_name="muted-text"))),
                columns=rx.breakpoints(initial="1",lg="2"),gap="15px",width="100%"),
        width="100%",spacing="5",align_items="stretch")


def ingestion_view():
    return rx.vstack(section_title("Data ingress","VALIDATED / ATOMIC / IDEMPOTENT"),
        rx.grid(
            panel(rx.hstack(icon("file-up",24,"#d7fd65"),section_title("Structured data import","CSV AND JSON"),gap="12px"),
                  rx.text("Upload exactly one entity type per file. All records must pass validation; a bad record rolls the whole batch back.",class_name="muted-text"),
                  rx.upload(rx.vstack(icon("upload-cloud",31,"#d7fd65"),
                          rx.text("DROP CSV / JSON FILE HERE",class_name="item-title"),
                          rx.text("or click to choose • max 2 MB • 500 records",class_name="micro"),align_items="center",spacing="3"),
                      id="import_files",multiple=False,max_files=1,max_size=2000000,
                      accept={"text/csv":[".csv"],"application/json":[".json"]},class_name="dropzone"),
                  rx.foreach(rx.selected_files("import_files"),lambda name:rx.text(name,class_name="micro lime")),
                  rx.button("VALIDATE + IMPORT",on_click=State.import_files(rx.upload_files(upload_id="import_files")),class_name="action-primary"),
                  rx.text(State.import_status,class_name="muted-text")),
            panel(rx.hstack(icon("webhook",24,"#d7fd65"),section_title("Carrier webhook simulator","SIGNED HTTP ENDPOINT ALSO PROVIDED"),gap="12px"),
                  rx.text("Endpoint: POST /carrier/webhook • header: x-carrier-token. Browser simulation enforces operations RBAC.",class_name="muted-text"),
                  rx.text_area(placeholder='{"event_id":"carrier-77","tracking":"SHP-1001","revision":10,"eta":"2026-11-08T00:00:00+00:00","occurred_at":"2026-10-28T00:00:00+00:00"}',
                      value=State.webhook_json,on_change=State.set_webhook_json,class_name="dark-textarea",min_height="170px",width="100%"),
                  rx.button("SIMULATE WEBHOOK PAYLOAD",on_click=State.ingest_json,class_name="outline-button")),
            columns=rx.breakpoints(initial="1",lg="2"),width="100%",gap="15px"
        ),
        panel(top_label("IMPORT CONTRACT"),rx.text("JSON: {\"entity\":\"orders\",\"records\":[{...}]}. CSV: filename orders.csv; header must match required fields exactly.",class_name="muted-text"),
              rx.text("Supported: suppliers, warehouses, supplier_skus, inventory, purchase_orders, shipments, orders. IDs use foreign keys and duplicates reject atomically.",class_name="muted-text")),
        width="100%",spacing="5",align_items="stretch"
    )


def audit_row(item):
    return rx.hstack(rx.vstack(rx.text(item["action"],class_name="mono-title"),rx.text(item["entity_type"]," / ",item["entity_id"],class_name="table-secondary"),spacing="0",width="210px"),
        rx.spacer(),rx.text(item["by_name"],class_name="micro"),rx.text(item["date_short"],class_name="micro"),
        width="100%",align_items="center",class_name="network-row")


def notification_row(item):
    return rx.hstack(rx.box(class_name="pulse-dot"),rx.text(item["message"],class_name="muted-text"),rx.spacer(),
            rx.cond(item["is_read"]==0,rx.button("ACK",on_click=State.mark_read(item["id"]),class_name="text-action")),
            width="100%",align_items="center",class_name="network-row")


def audit_view():
    return rx.vstack(section_title("Immutable event ledger","WHO / WHAT / WHEN / TRANSITION"),
        rx.grid(panel(section_title("Activity trail","LATEST 100 LOGGED EVENTS"),rx.foreach(State.audits,audit_row)),
                panel(section_title("Operator notifications","TARGETED BY ROLE"),rx.foreach(State.notifications,notification_row)),
                columns=rx.breakpoints(initial="1",lg="2"),gap="16px",width="100%"),
        width="100%",spacing="5",align_items="stretch")


def workspace():
    return rx.hstack(sidebar(),
        rx.box(
            app_header(),
            rx.cond(State.message!="",rx.hstack(icon("activity",16,"#d7fd65"),
               rx.text(State.message),rx.spacer(),rx.button(icon("x",13),on_click=State.set_message(""),variant="ghost"),
               class_name="message-banner",width="100%")),
            rx.cond(State.tab=="overview",overview()),
            rx.cond(State.tab=="disruptions",disruptions_view()),
            rx.cond(State.tab=="orders",orders_view()),
            rx.cond(State.tab=="recovery",recovery_view()),
            rx.cond(State.tab=="optimizer",optimization_view()),
            rx.cond(State.tab=="approvals",approval_view()),
            rx.cond(State.tab=="network",network_view()),
            rx.cond(State.tab=="ingest",ingestion_view()),
            rx.cond(State.tab=="audit",audit_view()),
            class_name="work-area",flex="1",min_width="0"
        ),class_name="app-shell",width="100%",align_items="stretch",spacing="0"
    )


def index() -> rx.Component:
    return rx.box(rx.cond(State.authenticated,workspace(),login_screen()),class_name="root",min_height="100vh")


app=rx.App(
    api_transformer=carrier_api,
    stylesheets=["/styles.css"],
    theme=rx.theme(appearance="dark",accent_color="lime",radius="medium"),
)
app.add_page(
    index,
    route="/",
    title="NaviPulse | Supply Chain Recovery Orchestrator",
    on_load=State.load,
)