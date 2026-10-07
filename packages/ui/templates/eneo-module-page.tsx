import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Heading } from "@astryxdesign/core/Heading";
import { Layout, LayoutContent } from "@astryxdesign/core/Layout";
import { List, ListItem } from "@astryxdesign/core/List";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { Brand, ModuleShell } from "@eneo-ai/module-kit";

/** Place this page inside RequireSession; the route owns loading, errors and data. */
export default function EneoModulePage({
  productName = "Eneo-modul",
  flows = [],
}: {
  productName?: string;
  flows?: readonly { id: string; name: string; description?: string | null }[];
}) {
  return (
    <ModuleShell label={productName} heading={<Brand productName={productName} />}>
      <Layout height="auto" contentWidth={960} padding={4}>
        <LayoutContent isScrollable={false}>
          <VStack gap={6} paddingBlockStart={4}>
            <Heading level={1}>Flöden</Heading>
            {flows.length === 0 ? (
              <EmptyState headingLevel={2} title="Det finns inga flöden att visa än." />
            ) : (
              <List hasDividers aria-label="Flöden">
                {flows.map((flow) => (
                  <ListItem
                    key={flow.id}
                    label={<Text weight="semibold">{flow.name}</Text>}
                    description={flow.description ? <Text type="supporting">{flow.description}</Text> : undefined}
                  />
                ))}
              </List>
            )}
          </VStack>
        </LayoutContent>
      </Layout>
    </ModuleShell>
  );
}
