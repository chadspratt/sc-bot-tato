# Bottato Architecture

## Composition / Ownership

```mermaid
graph TD

    subgraph Army
        Military["Military"]
        InitialScout["InitialScout"]
        Scout["Scout"]
        FormationSquad["FormationSquad"]
        Bunker["Bunker"]
        StuckRescue["StuckRescue"]
        Scouting["Scouting"]
        Formation["Formation"]
        Squad["Squad"]
        HarassSquad["HarassSquad"]
        HuntingSquad["HuntingSquad"]
        ParentFormation["ParentFormation"]
        MedivacDropSquad["MedivacDropSquad"]
    end
    
    subgraph Strategy
        Tactics["Tactics"]
        Enemy["Enemy"]
        EnemyIntel["EnemyIntel"]
        Map["Map"]
        InfluenceMaps["InfluenceMaps"]
        Zone["Zone"]
        Path["Path"]
    end

    subgraph Macro
        BuildOrder["BuildOrder"]
        BuildStep["BuildStep"]
        SCVBuildStep["SCVBuildStep"]
        StructureBuildStep["StructureBuildStep"]
        UpgradeBuildStep["UpgradeBuildStep"]
        SpecialLocations["SpecialLocations"]
        BuildStarts["BuildStarts"]
        Counter["Counter"]
        Upgrades["Upgrades"]
        TechTree["TechTree"]
        Workers["Workers"]
        Minerals["Minerals"]
        Vespene["Vespene"]
        Production["Production"]
        Facility["Facility"]
    end

    subgraph Micro
        MicroFactory["MicroFactory"]
        BaseUnitMicro["BaseUnitMicro"]
        MarineMicro["MarineMicro"]
        MarauderMicro["MarauderMicro"]
        MedivacMicro["MedivacMicro"]
        SiegeTankMicro["SiegeTankMicro"]
        OtherMicros["... BansheeMicro\nGhostMicro\nHellionMicro\nRavenMicro\nReaperMicro\nSCVMicro\nVikingMicro\nWidowMineMicro"]
    end

    subgraph Data["Data / Utilities"]
        UnitTypes["UnitTypes"]
        Enums["Enums"]
        Mixins["GeometryMixin\nDebugMixin"]
        LogHelper["LogHelper"]
        UnitReferenceHelper["UnitReferenceHelper"]
    end

    BotTato --> Commander

    %% Commander creates
    Commander --> Tactics
    Commander --> StructureMicro
    Commander --> Workers
    Commander --> Military
    Commander --> BuildOrder
    Commander --> Scouting

    Tactics --> Enemy
    Tactics --> Map
    Tactics --> EnemyIntel

    %% Military creates
    Military --> Squad
    Military -.-> Tactics
    Military -.-> Workers

    Squad --> FormationSquad
    Squad --> Bunker
    Squad --> HarassSquad
    Squad --> HuntingSquad
    Squad --> StuckRescue
    Squad --> MedivacDropSquad

    %% BuildOrder creates/refs
    BuildOrder --> Counter
    BuildOrder --> Upgrades
    BuildOrder --> SpecialLocations
    BuildOrder --> BuildStep
    BuildStep --> SCVBuildStep
    BuildStep --> StructureBuildStep
    BuildStep --> UpgradeBuildStep
    BuildOrder -.-> Workers
    BuildOrder -.-> Production
    BuildOrder -.-> Military
    BuildOrder -.-> Tactics

    %% Workers
    Workers --> Minerals
    Workers --> Vespene
    Workers -.-> Tactics

    %% Production
    Production --> Facility

    %% Map
    Map --> InfluenceMaps
    Map --> Zone
    Zone --> Path

    %% Scouting
    Scouting --> Scout
    Scouting --> InitialScout
    Scouting -.-> Tactics
    Scouting -.-> Workers
    Scouting -.-> Military

    %% Squad internals
    FormationSquad --> ParentFormation
    ParentFormation --> Formation

    %% Micro
    MicroFactory --> BaseUnitMicro
    BaseUnitMicro --> MarineMicro
    BaseUnitMicro --> MarauderMicro
    BaseUnitMicro --> MedivacMicro
    BaseUnitMicro --> SiegeTankMicro
    BaseUnitMicro --> OtherMicros

    %% Data references
    BuildOrder -.-> TechTree
    Upgrades -.-> TechTree
```

## Inheritance

```mermaid
classDiagram
    class BotAI
    class BotTato
    BotAI <|-- BotTato

    class Squad
    Squad <|-- FormationSquad
    Squad <|-- Bunker
    Squad <|-- HarassSquad
    Squad <|-- HuntingSquad
    Squad <|-- Scouting
    Squad <|-- Scout
    Squad <|-- InitialScout
    Squad <|-- EnemySquad
    Squad <|-- StuckRescue

    class BuildStep
    BuildStep <|-- SCVBuildStep
    BuildStep <|-- StructureBuildStep
    BuildStep <|-- UpgradeBuildStep

    class BaseUnitMicro
    BaseUnitMicro <|-- StructureMicro
    BaseUnitMicro <|-- MarineMicro
    BaseUnitMicro <|-- MarauderMicro
    BaseUnitMicro <|-- MedivacMicro
    BaseUnitMicro <|-- SiegeTankMicro
    BaseUnitMicro <|-- BansheeMicro
    BaseUnitMicro <|-- GhostMicro
    BaseUnitMicro <|-- HellionMicro
    BaseUnitMicro <|-- RavenMicro
    BaseUnitMicro <|-- ReaperMicro
    BaseUnitMicro <|-- SCVMicro
    BaseUnitMicro <|-- VikingMicro
    BaseUnitMicro <|-- WidowMineMicro

    class Resources
    Resources <|-- Minerals
    Resources <|-- Vespene
```

## Game Loop Flow

```mermaid
sequenceDiagram
    participant BT as BotTato
    participant CMD as Commander
    participant BO as BuildOrder
    participant MIL as Military
    participant SC as Scouting
    participant W as Workers
    participant P as Production
    participant MF as MicroFactory

    BT->>BT: on_step(iteration)
    BT->>BT: update_unit_references()
    BT->>CMD: command(iteration)
    CMD->>CMD: update_references()
    CMD->>SC: scout(iteration)
    CMD->>BO: execute()
    BO->>BO: evaluate_build_queue()
    BO->>W: allocate workers
    BO->>P: queue units
    CMD->>MIL: manage_army()
    MIL->>MIL: assign squads
    MIL->>MF: get_micro(unit_type)
    MF-->>MIL: micro instance
    MIL->>MIL: execute micro per unit
    CMD->>W: manage_workers()
```
